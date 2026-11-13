/**
 * RunPrefilter — run Williams trend test and Dunnett's pairwise comparisons
 *                on dose-response data via BMDExpress-native statistics.
 *
 * This is a standalone Java CLI tool that exposes the statistical functions
 * from sciome-commons-math (the same library BMDExpress 3 uses internally)
 * as a JSON-in / JSON-out pipeline.  The Python layer calls this instead of
 * reimplementing Williams/Dunnett in SciPy.
 *
 * Why Java instead of Python?
 *   - BMDExpress-native: these are the exact same statistical routines that
 *     run inside BMDExpress's prefilter step.  Using them ensures numerical
 *     parity with BMDExpress's own results.
 *   - The Williams trend test uses a permutation-based approach with
 *     multithreaded Monte Carlo — reimplementing this in Python would be
 *     slower and harder to validate.
 *   - Dunnett's test uses a multivariate-t distribution (also Monte Carlo).
 *
 * Statistical pipeline (mirrors NTP convention):
 *   1. Williams trend test — tests for a monotonic dose-response relationship.
 *      Returns a per-probe p-value (unadjusted and BH-adjusted).
 *      This replaces Jonckheere as the trend gatekeeper.
 *   2. Dunnett's test — pairwise comparisons of each dose group vs control.
 *      Returns a p-value for each non-control dose group per probe.
 *   3. Fold change — max absolute fold change (treatment mean / control mean)
 *      computed per probe, with per-dose fold changes.
 *
 * Input (JSON on stdin):
 *   {
 *     "doses": [0, 0, 0, 1, 1, 1, 3, 3, 3, 10, 10, 10],
 *     "probe_ids": ["probe_A", "probe_B", ...],
 *     "responses": [
 *       [1.2, 1.3, 1.1, 2.0, 2.1, 1.9, 3.0, 3.1, 2.9, 4.0, 4.1, 3.9],
 *       [5.0, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 5.9, 6.0, 6.1],
 *       ...
 *     ],
 *     "num_permutations": 1000,
 *     "num_threads": 4,
 *     "dunnett_simulations": 15000,
 *     "log_transform": "none"
 *   }
 *
 *   - doses: one value per sample (column), in the same order as response columns
 *   - probe_ids: one label per row in the responses matrix
 *   - responses: 2D array [n_probes × n_samples]
 *   - num_permutations: for Williams trend test (default 1000)
 *   - num_threads: parallelism for Williams (default 4)
 *   - dunnett_simulations: Monte Carlo iterations for Dunnett's (default 15000)
 *   - log_transform: "none", "base2", "base10", or "natural" (for fold change)
 *
 * Output (JSON to stdout):
 *   {
 *     "probes": [
 *       {
 *         "probe_id": "probe_A",
 *         "williams_p": 0.001,
 *         "williams_adjusted_p": 0.003,
 *         "dunnett_p": { "1.0": 0.42, "3.0": 0.01, "10.0": 0.0001 },
 *         "best_fold_change": 3.3,
 *         "fold_changes": { "1.0": 1.5, "3.0": 2.4, "10.0": 3.3 },
 *         "noel_dose": 1.0,
 *         "loel_dose": 3.0
 *       },
 *       ...
 *     ],
 *     "doses_unique": [0.0, 1.0, 3.0, 10.0],
 *     "n_probes": 2,
 *     "status": "ok"
 *   }
 *
 * Usage:
 *   echo '<json>' | java -cp <classpath>:java/ RunPrefilter
 *   # or:
 *   java -cp <classpath>:java/ RunPrefilter < input.json > output.json
 *
 * Pre-compile:
 *   javac -cp <classpath> java/RunPrefilter.java -d java/
 */

import java.io.*;
import java.util.*;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;

import org.apache.commons.math3.linear.MatrixUtils;
import org.apache.commons.math3.linear.RealMatrix;
import org.apache.commons.math3.linear.RealVector;

import com.sciome.commons.math.williams.WilliamsTrendTestResult;
import com.sciome.commons.math.williams.WilliamsTrendTestUtil;
import com.sciome.commons.math.dunnetts.DunnettsTest;


public class RunPrefilter {

    public static void main(String[] args) throws Exception {
        // Use IntegrateProject's NaN-safe mapper so that NaN values
        // (from Dunnett's zero-variance edge cases) serialize as JSON null
        // instead of the bare "NaN" token which becomes a string in Python.
        ObjectMapper mapper = IntegrateProject.createNanSafeMapper();

        // --- Read input JSON from stdin ---
        JsonNode input = mapper.readTree(System.in);

        // Parse dose vector — one value per sample (column in the matrix)
        JsonNode dosesNode = input.get("doses");
        double[] doseVector = new double[dosesNode.size()];
        for (int i = 0; i < dosesNode.size(); i++) {
            doseVector[i] = dosesNode.get(i).asDouble();
        }
        int nSamples = doseVector.length;

        // Parse probe IDs
        JsonNode probeIdsNode = input.get("probe_ids");
        String[] probeIds = new String[probeIdsNode.size()];
        for (int i = 0; i < probeIdsNode.size(); i++) {
            probeIds[i] = probeIdsNode.get(i).asText();
        }
        int nProbes = probeIds.length;

        // Parse response matrix [n_probes × n_samples]
        JsonNode responsesNode = input.get("responses");
        double[][] numericMatrix = new double[nProbes][nSamples];
        for (int i = 0; i < nProbes; i++) {
            JsonNode row = responsesNode.get(i);
            for (int j = 0; j < nSamples; j++) {
                numericMatrix[i][j] = row.get(j).asDouble();
            }
        }

        // Optional parameters with defaults
        int numPermutations = input.has("num_permutations")
            ? input.get("num_permutations").asInt() : 1000;
        int numThreads = input.has("num_threads")
            ? input.get("num_threads").asInt() : 4;
        int dunnettSims = input.has("dunnett_simulations")
            ? input.get("dunnett_simulations").asInt() : 15000;
        String logTransform = input.has("log_transform")
            ? input.get("log_transform").asText() : "none";

        // Williams p-value cutoff — only probes with Williams p below this
        // threshold get Dunnett's pairwise test.  This mirrors BMDExpress's
        // own prefilter pipeline: Williams is the gatekeeper, and Dunnett's
        // (which is expensive: Monte Carlo per probe per dose group) only
        // runs on probes that show a significant trend.
        // Default 0.05 matches BMDExpress's default p-value cutoff.
        double williamsPCutoff = input.has("williams_p_cutoff")
            ? input.get("williams_p_cutoff").asDouble() : 0.05;

        // Determine log transformation parameters for fold change calculation.
        // BMDExpress computes fold change in the original (non-log) scale:
        //   fold_change = treatment_mean / control_mean  (if data is not log-transformed)
        //   fold_change = base^(treatment_mean - control_mean) (if data IS log-transformed)
        // For the "none" case we just use the ratio directly.
        boolean isLogTransformed = !logTransform.equals("none");
        double logBase = 2.0;
        if (logTransform.equals("base10")) logBase = 10.0;
        else if (logTransform.equals("natural")) logBase = Math.E;

        // --- Identify unique dose groups ---
        // Build a sorted list of unique doses + a mapping from dose → sample indices.
        // This is needed for Dunnett's (which wants per-group arrays) and fold change.
        TreeMap<Double, List<Integer>> doseGroupIndices = new TreeMap<>();
        for (int j = 0; j < nSamples; j++) {
            doseGroupIndices.computeIfAbsent(doseVector[j], k -> new ArrayList<>()).add(j);
        }
        List<Double> uniqueDoses = new ArrayList<>(doseGroupIndices.keySet());
        double controlDose = uniqueDoses.get(0);  // Lowest dose = control
        List<Double> treatmentDoses = uniqueDoses.subList(1, uniqueDoses.size());

        System.err.println("  RunPrefilter: " + nProbes + " probes × "
                           + nSamples + " samples, "
                           + uniqueDoses.size() + " dose groups");
        System.err.println("  Williams permutations=" + numPermutations
                           + ", Dunnett simulations=" + dunnettSims
                           + ", threads=" + numThreads
                           + ", Williams p cutoff=" + williamsPCutoff);

        // --- Step 1: Williams trend test ---
        // williamsUtil.williams() takes the full matrix and dose vector,
        // runs a permutation-based Williams trend test for every probe
        // simultaneously.  Returns per-probe p-values and adjusted p-values.
        WilliamsTrendTestUtil williamsUtil = new WilliamsTrendTestUtil();
        RealMatrix matrix = MatrixUtils.createRealMatrix(numericMatrix);
        RealVector doseVec = MatrixUtils.createRealVector(doseVector);

        System.err.println("  Running Williams trend test...");
        WilliamsTrendTestResult williamsResult = williamsUtil.williams(
            matrix, doseVec,
            23524,                // random seed (same as BMDExpress uses)
            numPermutations,
            null,                 // no covariate matrix
            numThreads,
            null                  // no progress updater
        );

        if (williamsResult == null) {
            // Williams can return null if the matrix is degenerate
            ObjectNode errorOut = mapper.createObjectNode();
            errorOut.put("status", "error");
            errorOut.put("message", "Williams trend test returned null — "
                         + "check that the dose-response matrix is valid");
            mapper.writeValue(System.out, errorOut);
            System.exit(1);
        }

        // --- Step 2: Dunnett's test + fold change per probe ---
        // Dunnett's expects: control double[], treatment double[][] (one array per dose group).
        // We run it per-probe because each probe has its own response values.
        DunnettsTest dunnetts = new DunnettsTest();
        List<Integer> controlIndices = doseGroupIndices.get(controlDose);

        // Pre-build the treatment dose group structure (same for all probes)
        int nTreatmentGroups = treatmentDoses.size();

        // Track how many probes pass the Williams gate for Dunnett's
        int dunnettCount = 0;

        // Output array
        ArrayNode probesOut = mapper.createArrayNode();

        for (int i = 0; i < nProbes; i++) {
            ObjectNode probeOut = mapper.createObjectNode();
            probeOut.put("probe_id", probeIds[i]);

            // Williams results
            double wp = williamsResult.getpValue().getEntry(i);
            double wap = williamsResult.getAdjustedPValue().getEntry(i);
            probeOut.put("williams_p", wp);
            probeOut.put("williams_adjusted_p", wap);

            // Extract per-group response values for this probe
            double[] controlVals = new double[controlIndices.size()];
            for (int c = 0; c < controlIndices.size(); c++) {
                controlVals[c] = numericMatrix[i][controlIndices.get(c)];
            }

            double[][] treatmentVals = new double[nTreatmentGroups][];
            for (int g = 0; g < nTreatmentGroups; g++) {
                List<Integer> indices = doseGroupIndices.get(treatmentDoses.get(g));
                treatmentVals[g] = new double[indices.size()];
                for (int k = 0; k < indices.size(); k++) {
                    treatmentVals[g][k] = numericMatrix[i][indices.get(k)];
                }
            }

            // Run Dunnett's test only if Williams trend is significant.
            // This mirrors BMDExpress's prefilter pipeline: Williams is the
            // gatekeeper for whether a probe proceeds to pairwise testing.
            // Dunnett's is expensive (Monte Carlo per probe × dose group),
            // so skipping non-significant probes saves substantial time
            // on large genomic datasets (e.g., 2000 probes → ~200 pass).
            ObjectNode dunnettPvals = mapper.createObjectNode();
            if (wp <= williamsPCutoff) {
                dunnettCount++;
                try {
                    double[] pVals = dunnetts.dunnettsTest(controlVals, treatmentVals, dunnettSims);
                    for (int g = 0; g < nTreatmentGroups; g++) {
                        dunnettPvals.put(String.valueOf(treatmentDoses.get(g)), pVals[g]);
                    }
                } catch (Exception e) {
                    // If Dunnett's fails (e.g., all values identical), report NaN
                    System.err.println("  WARNING: Dunnett's failed for probe "
                                       + probeIds[i] + ": " + e.getMessage());
                    for (int g = 0; g < nTreatmentGroups; g++) {
                        dunnettPvals.put(String.valueOf(treatmentDoses.get(g)), Double.NaN);
                    }
                }
            }
            // If Williams was not significant, dunnett_p is an empty object —
            // the Python layer treats missing p-values as non-significant.
            probeOut.set("dunnett_p", dunnettPvals);

            // --- Step 3: Fold change ---
            // Compute fold change for each treatment dose group vs control.
            // For non-log data: fold_change = treatment_mean / control_mean
            // For log data:     fold_change = base^(treatment_mean - control_mean)
            double controlMean = mean(controlVals);
            ObjectNode foldChanges = mapper.createObjectNode();
            double bestFoldChange = 0.0;

            for (int g = 0; g < nTreatmentGroups; g++) {
                double treatMean = mean(treatmentVals[g]);
                double fc;
                if (isLogTransformed) {
                    // Data is in log scale — fold change in original scale
                    fc = Math.pow(logBase, treatMean - controlMean);
                } else {
                    // Data is in original scale — simple ratio
                    if (controlMean != 0.0) {
                        fc = treatMean / controlMean;
                    } else {
                        fc = Double.NaN;
                    }
                }
                foldChanges.put(String.valueOf(treatmentDoses.get(g)), fc);
                if (Math.abs(fc) > Math.abs(bestFoldChange)) {
                    bestFoldChange = fc;
                }
            }
            probeOut.set("fold_changes", foldChanges);
            probeOut.put("best_fold_change", bestFoldChange);

            // --- Step 4: NOEL/LOEL ---
            // Walk dose groups from lowest to highest.  The LOEL is the first
            // dose where BOTH the Dunnett's p-value < threshold AND fold change
            // exceeds the threshold.  The NOEL is the dose just below LOEL.
            // We use the NTP defaults: p < 0.05, fold change > 1.0 (no filter).
            // These thresholds match BMDExpress's PrefilterService defaults.
            double noelLoelPThreshold = 0.05;
            double noelLoelFcThreshold = 0.0;  // No fold change filter by default
            Double noelDose = null;
            Double loelDose = null;

            // Only compute NOEL/LOEL if Dunnett's was run (probe passed Williams gate)
            JsonNode dunnettPNode = probeOut.get("dunnett_p");
            for (int g = 0; g < nTreatmentGroups; g++) {
                String doseKey = String.valueOf(treatmentDoses.get(g));
                JsonNode pNode = dunnettPNode.get(doseKey);
                if (pNode == null) continue;  // No Dunnett's for this probe
                double pVal = pNode.asDouble(1.0);
                double fc = foldChanges.get(doseKey).asDouble(0.0);

                if (pVal < noelLoelPThreshold && Math.abs(fc) > noelLoelFcThreshold) {
                    // This dose group is significantly different from control
                    if (g == 0) {
                        noelDose = controlDose;
                    } else {
                        noelDose = treatmentDoses.get(g - 1);
                    }
                    loelDose = treatmentDoses.get(g);
                    break;
                }
            }

            if (noelDose != null) probeOut.put("noel_dose", noelDose);
            if (loelDose != null) probeOut.put("loel_dose", loelDose);

            probesOut.add(probeOut);
        }

        // --- Assemble output ---
        ObjectNode root = mapper.createObjectNode();
        root.put("status", "ok");
        root.put("n_probes", nProbes);

        ArrayNode dosesOutArr = mapper.createArrayNode();
        for (double d : uniqueDoses) dosesOutArr.add(d);
        root.set("doses_unique", dosesOutArr);

        root.set("probes", probesOut);

        // Write to stdout
        mapper.writeValue(System.out, root);
        System.err.println("  RunPrefilter complete: " + dunnettCount + "/"
                           + nProbes + " probes passed Williams gate for Dunnett's.");
    }

    /**
     * Simple arithmetic mean of an array of doubles.
     * Returns NaN for empty arrays (which shouldn't happen in practice).
     */
    private static double mean(double[] values) {
        if (values.length == 0) return Double.NaN;
        double sum = 0;
        for (double v : values) sum += v;
        return sum / values.length;
    }
}
