/**
 * RunApicalBmds — fit apical continuous BMD models via the BMDExpress ToxicR engine.
 *
 * Standalone JSON-in / JSON-out CLI, same mold as RunPrefilter: the Python layer
 * pipes per-endpoint dose-response data on stdin and reads BMD/BMDL results on
 * stdout. This replaces the Python `pybmds` recompute (tables/apical_bmds.py) with
 * the SAME native engine BMDExpress itself uses (ToxicR via libDRBMD.so), so the
 * numbers are BMDExpress-identical rather than an EPA-BMDS approximation.
 *
 * Requires the native library on java.library.path:
 *   java -Djava.library.path=$BMDX_PROJECT_ROOT -cp <cp>:<helperdir> RunApicalBmds
 * (ToxicRJNI does System.loadLibrary("DRBMD").)
 *
 * The fit CONFIG is per-endpoint, extracted by the Python caller from each
 * bMDResult.analysisInfo (Models fit / BMR Type / BMR Factor / Constant Variance),
 * so an endpoint is modeled with the SAME settings its .bm2 was — which is what makes
 * the downstream overlap comparison (hard-stop validation) like-for-like.
 *
 * Input (JSON on stdin):
 *   {
 *     "endpoints": [
 *       {
 *         "key": "Male::Total Thyroxine",
 *         "doses": [0,0,0,0, 4,4,4,4, 37,37,37, 111,111,111],   // per-animal
 *         "Y":     [10.1,9.8,...],                               // per-animal, same length
 *         "models": [6,8,3,5],          // HILL,POWER,EXP3,EXP5 (from "Models fit")
 *         "bmr_type": 2,                // 1=Standard Deviation, 2=Relative Deviation
 *         "bmr_factor": 0.25,           // "BMR Factor"
 *         "is_ncv": false               // "Constant Variance: 1" -> false
 *       }, ...
 *     ]
 *   }
 *
 * Output (JSON on stdout): { "<key>": {bmd, bmdl, bmdu, r_squared, model_name, status, notes}, ... }
 *   A completed fit has status null: the caller (bmdx_pipe.apical_stats.run_apical_bmds_java)
 *   classifies it with bmdx_pipe.bmd_acceptance, the one place the report's acceptance
 *   criteria live.  A fit that could not run or produced no BMD is status "NVM".
 *   r_squared is BMDExpress's R² of the model average against the dose-group means
 *   (BMDStatisticsService.calculateRSquared over calculateResiduals).
 */

import java.util.ArrayList;
import java.util.List;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;

import com.sciome.bmdexpress2.mvp.model.LogTransformationEnum;
import com.sciome.bmdexpress2.mvp.model.stat.ModelAveragingResult;
import com.sciome.bmdexpress2.util.bmds.BMDSToxicRUtils;

public class RunApicalBmds {

    public static void main(String[] args) throws Exception {
        // NaN -> JSON null, matching RunPrefilter/IntegrateProject so Python sees null.
        ObjectMapper mapper = IntegrateProject.createNanSafeMapper();
        JsonNode input = mapper.readTree(System.in);
        JsonNode endpoints = input.get("endpoints");

        ObjectNode out = mapper.createObjectNode();

        for (JsonNode ep : endpoints) {
            String key = ep.get("key").asText();
            try {
                out.set(key, fitEndpoint(mapper, ep));
            } catch (Throwable t) {
                // Never let one endpoint's failure abort the batch — emit an NVM row
                // with the reason, exactly as the pybmds path returned _failure_result.
                out.set(key, failure(mapper, "fit error: " + t.getMessage()));
                System.err.println("RunApicalBmds: endpoint '" + key + "' failed: " + t);
            }
        }

        System.out.println(mapper.writeValueAsString(out));
    }

    private static ObjectNode fitEndpoint(ObjectMapper mapper, JsonNode ep) throws Exception {
        double[] doses = toDoubleArray(ep.get("doses"));
        double[] Y = toDoubleArray(ep.get("Y"));
        int[] models = toIntArray(ep.get("models"));
        int bmrType = ep.get("bmr_type").asInt();
        double bmrFactor = ep.get("bmr_factor").asDouble();
        boolean isNcv = ep.has("is_ncv") && ep.get("is_ncv").asBoolean();
        boolean isFast = ep.has("is_fast") && ep.get("is_fast").asBoolean();

        // --- computability gate (mirror of run_bmds_session validation) ---
        if (doses.length != Y.length || doses.length < 3) {
            return failure(mapper, "Insufficient data or mismatched dose/Y lengths");
        }
        // Need at least 3 distinct dose groups (control + 2 treatment).
        if (distinctCount(doses) < 3) {
            return failure(mapper, "Fewer than 3 distinct dose groups");
        }
        // Zero variance everywhere -> no dose-response to model.
        if (allEqual(Y)) {
            return failure(mapper, "Zero variance across all responses");
        }

        // Laplace model averaging, non-MCMC, transform NONE (apical data is not
        // log-transformed). bmrType 1/2 is remapped to ToxicR SD/REL inside.
        ModelAveragingResult ma = BMDSToxicRUtils.calculateToxicRMA(
                models, Y, doses, bmrType, bmrFactor, isNcv,
                /*useMCMC*/ false, isFast, LogTransformationEnum.NONE);

        double bmd = ma.getBMD();
        double bmdl = ma.getBMDL();
        double bmdu = ma.getBMDU();
        String modelName = (ma.getModelWithHighestPP() != null)
                ? ma.getModelWithHighestPP().getModel() : "Model Average";

        if (Double.isNaN(bmd) || Double.isInfinite(bmd)) {
            return failure(mapper, "BMD is NaN or Inf");
        }

        double r2 = rSquared(ma, doses, Y);

        ObjectNode r = mapper.createObjectNode();
        r.put("bmd", round3(bmd));
        r.put("bmdl", (Double.isNaN(bmdl) || bmdl <= 0) ? null : (Double) round3(bmdl));
        r.put("bmdu", (Double.isNaN(bmdu) || bmdu <= 0) ? null : (Double) round3(bmdu));
        r.put("r_squared", Double.isNaN(r2) ? null : (Double) r2);
        r.put("model_name", modelName);
        r.putNull("status");
        r.put("notes", "");
        return r;
    }

    /**
     * BMDExpress's R² of a fit: residuals are each dose group's mean response minus the
     * model-averaged curve at that dose; R² = 1 - SSR / SST, SST over the group means.
     * Reproduces the rSquared BMDExpress stores on bestStatResult (checked against every
     * apical endpoint of the NIEHS-13 non-genomic project).  NaN when the means are flat.
     */
    private static double rSquared(ModelAveragingResult ma, double[] doses, double[] Y) {
        List<Double> groupDoses = new ArrayList<>();
        List<double[]> sums = new ArrayList<>();  // {sum, n} per group
        for (int i = 0; i < doses.length; i++) {
            int g = groupDoses.indexOf(doses[i]);
            if (g < 0) {
                groupDoses.add(doses[i]);
                sums.add(new double[] {0, 0});
                g = groupDoses.size() - 1;
            }
            sums.get(g)[0] += Y[i];
            sums.get(g)[1] += 1;
        }
        int k = groupDoses.size();
        double[] means = new double[k];
        double avg = 0;
        for (int g = 0; g < k; g++) {
            means[g] = sums.get(g)[0] / sums.get(g)[1];
            avg += means[g] / k;
        }
        double ssr = 0, sst = 0;
        for (int g = 0; g < k; g++) {
            double res = means[g] - ma.getResponseAt(groupDoses.get(g));
            ssr += res * res;
            sst += (means[g] - avg) * (means[g] - avg);
        }
        return sst > 0 ? 1 - ssr / sst : Double.NaN;
    }

    private static ObjectNode failure(ObjectMapper mapper, String note) {
        ObjectNode r = mapper.createObjectNode();
        r.putNull("bmd");
        r.putNull("bmdl");
        r.putNull("bmdu");
        r.putNull("model_name");
        r.put("status", "NVM");
        r.put("notes", note);
        return r;
    }

    // --- helpers ---

    private static double[] toDoubleArray(JsonNode n) {
        double[] a = new double[n.size()];
        for (int i = 0; i < n.size(); i++) a[i] = n.get(i).asDouble();
        return a;
    }

    private static int[] toIntArray(JsonNode n) {
        int[] a = new int[n.size()];
        for (int i = 0; i < n.size(); i++) a[i] = n.get(i).asInt();
        return a;
    }

    private static int distinctCount(double[] a) {
        List<Double> seen = new ArrayList<>();
        for (double v : a) if (!seen.contains(v)) seen.add(v);
        return seen.size();
    }

    private static boolean allEqual(double[] a) {
        for (int i = 1; i < a.length; i++) if (a[i] != a[0]) return false;
        return true;
    }

    private static double round3(double v) {
        return Math.round(v * 1000.0) / 1000.0;
    }
}
