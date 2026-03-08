/**
 * ExportCategories — extract category analysis BMD values from a .bm2 file.
 *
 * Reads a BMDExpress 3 .bm2 file and extracts ALL category analysis results
 * (DEFINED, GO_BP, GENE, etc.) with their full set of BMD statistics.  This
 * replaces the broken DataCombinerService TSV export path which crashes with
 * IndexOutOfBoundsException.
 *
 * For each CategoryAnalysisResult (one endpoint/gene set), exports:
 *   - Category identifier (id, title, type)
 *   - All BMD statistics: mean, median, minimum, weighted mean, SD,
 *     5th/10th percentile, lower/upper 95% CI
 *   - Same for BMDL and BMDU
 *   - Gene counts, direction, Fisher's p-value, fold change
 *   - Gene symbols that passed all filters
 *
 * Output JSON structure:
 *   {
 *     "analyses": [
 *       {
 *         "name": "BodyWeightFemale_BMD_null_DEFINED-...",
 *         "experiment_prefix": "BodyWeightFemale",
 *         "category_type": "DEFINED",
 *         "results": [
 *           {
 *             "category_id": "Body Weight 6",
 *             "category_title": "SD5",
 *             "category_type": "generic",
 *             "bmd": { "mean": 0.00037, "median": 0.00037, "minimum": 0.00037,
 *                      "weighted_mean": 0.00037, "sd": null, "weighted_sd": null,
 *                      "fifth_pct": null, "tenth_pct": null,
 *                      "lower95": null, "upper95": null },
 *             "bmdl": { ... },
 *             "bmdu": { ... },
 *             "genes_passed": 1,
 *             "genes_total": 1,
 *             "direction": "up",
 *             "fishers_two_tail": 0.5,
 *             "max_fold_change": 1.8,
 *             "gene_symbols": "SD5"
 *           },
 *           ...
 *         ]
 *       },
 *       ...
 *     ]
 *   }
 *
 * Usage:
 *   java -cp <classpath>:java/ ExportCategories <bm2_path> <json_out>
 *
 * Pre-compile once:
 *   javac -cp <classpath> java/ExportCategories.java -d java/
 */

import java.io.*;
import java.util.*;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;

import com.sciome.bmdexpress2.mvp.model.BMDProject;
import com.sciome.bmdexpress2.mvp.model.category.CategoryAnalysisResult;
import com.sciome.bmdexpress2.mvp.model.category.CategoryAnalysisResults;
import com.sciome.bmdexpress2.mvp.model.category.ReferenceGeneProbeStatResult;
import com.sciome.bmdexpress2.mvp.model.stat.ProbeStatResult;
import com.sciome.bmdexpress2.mvp.model.category.identifier.CategoryIdentifier;
import com.sciome.bmdexpress2.mvp.model.category.identifier.GOCategoryIdentifier;
import com.sciome.bmdexpress2.mvp.model.category.identifier.GenericCategoryIdentifier;

public class ExportCategories {

    public static void main(String[] args) throws Exception {
        if (args.length < 2) {
            System.err.println("Usage: ExportCategories <bm2_path> <json_out>");
            System.exit(1);
        }

        String bm2Path = args[0];
        String jsonOut = args[1];

        // --- Deserialize the .bm2 file ---
        System.err.println("  Loading BMDProject from " + bm2Path + "...");
        BMDProject project;
        try (FileInputStream fileIn = new FileInputStream(new File(bm2Path));
             BufferedInputStream bIn = new BufferedInputStream(fileIn, 1024 * 2000);
             ObjectInputStream in = new ObjectInputStream(bIn)) {
            project = (BMDProject) in.readObject();
        }

        ObjectMapper mapper = IntegrateProject.createNanSafeMapper();

        ObjectNode root = mapper.createObjectNode();
        ArrayNode analyses = mapper.createArrayNode();

        List<CategoryAnalysisResults> catResultSets = project.getCategoryAnalysisResults();
        if (catResultSets == null) catResultSets = Collections.emptyList();

        int totalEndpoints = 0;

        for (CategoryAnalysisResults catResults : catResultSets) {
            String catName = catResults.getName();

            ObjectNode analysisNode = mapper.createObjectNode();
            analysisNode.put("name", catName);

            // Extract experiment prefix: everything before "_BMD"
            // e.g. "BodyWeightFemale_BMD_null_DEFINED-..." → "BodyWeightFemale"
            String prefix = catName.contains("_BMD")
                ? catName.split("_BMD")[0]
                : catName;
            analysisNode.put("experiment_prefix", prefix);

            // Determine category type from analysis name.
            // BMDExpress names contain "DEFINED-Category", "GO_BP", "GO_CC",
            // "GO_MF", "REACTOME", "GENE", etc.
            String categoryType = detectCategoryType(catName);
            analysisNode.put("category_type", categoryType);

            // Iterate all individual category results (one per endpoint/gene set)
            // Note: BMDExpress has a typo in the getter — "Analsyis" not "Analysis"
            @SuppressWarnings("deprecation")
            List<CategoryAnalysisResult> results = catResults.getCategoryAnalsyisResults();
            if (results == null) results = Collections.emptyList();

            ArrayNode resultsArray = mapper.createArrayNode();

            for (CategoryAnalysisResult car : results) {
                ObjectNode entry = mapper.createObjectNode();

                // Category identifier — id and human-readable title
                CategoryIdentifier ci = car.getCategoryIdentifier();
                entry.put("category_id", ci.getId());
                entry.put("category_title", ci.getTitle());

                // Tag the identifier type for downstream filtering
                if (ci instanceof GOCategoryIdentifier) {
                    entry.put("identifier_type", "go");
                    String level = ((GOCategoryIdentifier) ci).getGoLevel();
                    if (level != null) {
                        try {
                            entry.put("go_level", Integer.parseInt(level));
                        } catch (NumberFormatException e) {
                            entry.put("go_level", level);
                        }
                    }
                } else if (ci instanceof GenericCategoryIdentifier) {
                    entry.put("identifier_type", "generic");
                } else {
                    entry.put("identifier_type", ci.getClass().getSimpleName());
                }

                // --- BMD statistics (all variants) ---
                // Each comes as a nested object with mean, median, minimum, etc.
                // Use the *TotalGenes variants for 5th/10th percentile —
                // the short-named getters (getBmdFifthPercentile etc.) are
                // transient fields that are null after Java deserialization.
                // The TotalGenes variants are the persisted fields with data.
                entry.set("bmd", buildStatBlock(mapper, car,
                    car.getBmdMean(), car.getBmdMedian(), car.getBmdMinimum(),
                    car.getBmdWMean(), car.getBmdSD(), car.getBmdWSD(),
                    car.getBmdFifthPercentileTotalGenes(), car.getBmdTenthPercentileTotalGenes(),
                    car.getbmdLower95(), car.getbmdUpper95()));

                entry.set("bmdl", buildStatBlock(mapper, car,
                    car.getBmdlMean(), car.getBmdlMedian(), car.getBmdlMinimum(),
                    car.getBmdlWMean(), car.getBmdlSD(), car.getBmdlWSD(),
                    car.getBmdlFifthPercentileTotalGenes(), car.getBmdlTenthPercentileTotalGenes(),
                    car.getbmdlLower95(), car.getbmdlUpper95()));

                entry.set("bmdu", buildStatBlock(mapper, car,
                    car.getBmduMean(), car.getBmduMedian(), car.getBmduMinimum(),
                    car.getBmduWMean(), car.getBmduSD(), car.getBmduWSD(),
                    car.getBmduFifthPercentileTotalGenes(), car.getBmduTenthPercentileTotalGenes(),
                    car.getbmduLower95(), car.getbmduUpper95()));

                // --- Gene counts and filter results ---
                Integer passed = car.getGenesThatPassedAllFilters();
                Integer allCount = car.getGeneAllCount();
                entry.put("genes_passed", passed != null ? passed : 0);
                entry.put("genes_total", allCount != null ? allCount : 0);

                // ANOVA-significant gene count (pre-BMD filter)
                Integer anovaCount = car.getGeneCountSignificantANOVA();
                if (anovaCount != null) entry.put("genes_significant_anova", anovaCount);

                // --- Direction ---
                // The overallDirection field is transient (null after Java
                // deserialization), so we replicate the BMDExpress logic:
                // iterate per-gene adverse directions, apply 60% threshold.
                try {
                    var refs = car.getReferenceGeneProbeStatResults();
                    if (refs != null) {
                        int upcount = 0, downcount = 0, conflictcount = 0, totalcount = 0;
                        for (var rp : refs) {
                            int pupcount = 0, pdowncount = 0;
                            for (ProbeStatResult psr : rp.getProbeStatResults()) {
                                if (psr.getBestStatResult() != null) {
                                    short ad = psr.getBestStatResult().getAdverseDirection();
                                    if (ad == 1) pupcount++;
                                    else if (ad == -1) pdowncount++;
                                }
                            }
                            if (pupcount > 0 && pdowncount == 0) upcount++;
                            else if (pdowncount > 0 && pupcount == 0) downcount++;
                            else conflictcount++;
                            totalcount++;
                        }
                        if (totalcount > 0) {
                            if ((float) upcount / totalcount >= 0.6f)
                                entry.put("direction", "up");
                            else if ((float) downcount / totalcount >= 0.6f)
                                entry.put("direction", "down");
                            else
                                entry.put("direction", "conflict");
                        }
                    }
                } catch (Exception e) {
                    // Direction not available — leave field absent
                }

                // --- Fisher's exact test ---
                Double fishersLeft = car.getFishersExactLeftPValue();
                Double fishersRight = car.getFishersExactRightPValue();
                Double fishersTwoTail = car.getFishersExactTwoTailPValue();
                if (fishersLeft != null) entry.put("fishers_left", fishersLeft);
                if (fishersRight != null) entry.put("fishers_right", fishersRight);
                if (fishersTwoTail != null) entry.put("fishers_two_tail", fishersTwoTail);

                // --- Fold change ---
                // BMDExpress uses lowercase getters for fold change fields
                Double maxFC = car.getmaxFoldChange();
                Double meanFC = car.getmeanFoldChange();
                Double medianFC = car.getmedianFoldChange();
                if (maxFC != null) entry.put("max_fold_change", maxFC);
                if (meanFC != null) entry.put("mean_fold_change", meanFC);
                if (medianFC != null) entry.put("median_fold_change", medianFC);

                // --- Gene symbols ---
                String symbols = car.getGeneSymbols();
                if (symbols != null) entry.put("gene_symbols", symbols);

                // --- Up/Down gene counts ---
                Integer upCount = car.getGenesAdverseUpCount();
                Integer downCount = car.getGenesAdverseDownCount();
                if (upCount != null) entry.put("genes_up", upCount);
                if (downCount != null) entry.put("genes_down", downCount);

                resultsArray.add(entry);
                totalEndpoints++;
            }

            analysisNode.put("result_count", results.size());
            analysisNode.set("results", resultsArray);
            analyses.add(analysisNode);
        }

        root.put("analysis_count", catResultSets.size());
        root.put("total_endpoints", totalEndpoints);
        root.set("analyses", analyses);

        // Write output
        System.err.println("  Writing categories JSON to " + jsonOut + "...");
        System.err.println("  " + catResultSets.size() + " analyses, "
                           + totalEndpoints + " endpoints total.");
        mapper.writeValue(new File(jsonOut), root);
        System.err.println("  Done.");
    }

    /**
     * Build a statistics block for BMD, BMDL, or BMDU.
     *
     * Returns a JSON object with all the standard aggregate statistics
     * for one of the three benchmark dose values.  NaN values are
     * converted to null by IntegrateProject.createNanSafeMapper().
     */
    private static ObjectNode buildStatBlock(
            ObjectMapper mapper, CategoryAnalysisResult car,
            Double mean, Double median, Double minimum,
            Double weightedMean, Double sd, Double weightedSd,
            Double fifthPct, Double tenthPct,
            Double lower95, Double upper95) {
        ObjectNode block = mapper.createObjectNode();
        block.put("mean", mean);
        block.put("median", median);
        block.put("minimum", minimum);
        block.put("weighted_mean", weightedMean);
        block.put("sd", sd);
        block.put("weighted_sd", weightedSd);
        block.put("fifth_pct", fifthPct);
        block.put("tenth_pct", tenthPct);
        block.put("lower95", lower95);
        block.put("upper95", upper95);
        return block;
    }

    /**
     * Detect the category type from the analysis name.
     *
     * BMDExpress encodes the category type in the analysis name string:
     *   - "DEFINED-Category File-..." → defined (user-provided category file)
     *   - "...GO_BP..." → go_bp (Gene Ontology Biological Process)
     *   - "...GO_CC..." → go_cc (Gene Ontology Cellular Component)
     *   - "...GO_MF..." → go_mf (Gene Ontology Molecular Function)
     *   - "...REACTOME..." → reactome
     *   - Contains just gene-level BMD → gene
     */
    private static String detectCategoryType(String name) {
        String upper = name.toUpperCase();
        if (upper.contains("DEFINED-CATEGORY") || upper.contains("DEFINED_CATEGORY"))
            return "defined";
        if (upper.contains("GO_BP")) return "go_bp";
        if (upper.contains("GO_CC")) return "go_cc";
        if (upper.contains("GO_MF")) return "go_mf";
        if (upper.contains("REACTOME")) return "reactome";
        if (upper.contains("_GENE_") || upper.endsWith("_GENE")) return "gene";
        return "unknown";
    }
}
