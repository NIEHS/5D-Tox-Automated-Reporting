/**
 * ExportGenomics — extract gene-level BMD and GO category results from a .bm2 file.
 *
 * Reads a BMDExpress 3 .bm2 file (Java serialized BMDProject) and extracts
 * the genomics results that the report needs:
 *
 *   1. Per-probe (gene) BMD results: symbol, BMD, BMDL, BMDU, direction,
 *      rSquared, fold change — grouped by organ × sex experiment.
 *
 *   2. GO Biological Process category analysis: GO ID, term name, bmdMedian,
 *      bmdlMedian, gene count, direction, Fisher's p-value, member gene
 *      symbols — grouped by organ × sex experiment.
 *
 * Output is a single JSON file with this structure:
 *   {
 *     "experiments": [
 *       {
 *         "name": "Liver_PFHxSAm_Male_No0",
 *         "organ": "Liver",
 *         "sex": "Male",
 *         "total_probes": 1717,
 *         "genes": [
 *           { "probe_id": "ACAA1A_7954", "gene_symbol": "Acaa1a",
 *             "bmd": 12.5, "bmdl": 8.3, "bmdu": 18.2,
 *             "direction": "up", "r_squared": 0.95,
 *             "fold_change": 2.3, "fit_p_value": 0.001 },
 *           ...
 *         ],
 *         "go_bp": [
 *           { "go_id": "GO:0006629", "go_term": "lipid metabolic process",
 *             "bmd_median": 25.9, "bmdl_median": 16.5, "bmdu_median": 42.1,
 *             "n_genes": 111, "n_passed": 85, "direction": "up",
 *             "fishers_two_tail": 2.3e-23,
 *             "gene_symbols": "acox1;acaa1a;..." },
 *           ...
 *         ]
 *       }
 *     ]
 *   }
 *
 * Usage:
 *   java -cp <classpath>:java/ ExportGenomics <bm2_path> <json_out>
 *
 * Pre-compile once:
 *   javac -cp <classpath> java/ExportGenomics.java -d java/
 */

import java.io.*;
import java.util.*;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;

import com.sciome.bmdexpress2.mvp.model.BMDProject;
import com.sciome.bmdexpress2.mvp.model.DoseResponseExperiment;
import com.sciome.bmdexpress2.mvp.model.stat.BMDResult;
import com.sciome.bmdexpress2.mvp.model.stat.ProbeStatResult;
import com.sciome.bmdexpress2.mvp.model.stat.StatResult;
import com.sciome.bmdexpress2.mvp.model.category.CategoryAnalysisResult;
import com.sciome.bmdexpress2.mvp.model.category.CategoryAnalysisResults;
import com.sciome.bmdexpress2.mvp.model.category.GOAnalysisResult;
import com.sciome.bmdexpress2.mvp.model.category.identifier.CategoryIdentifier;
import com.sciome.bmdexpress2.mvp.model.category.identifier.GOCategoryIdentifier;

public class ExportGenomics {

    public static void main(String[] args) throws Exception {
        if (args.length < 2) {
            System.err.println("Usage: ExportGenomics <bm2_path> <json_out>");
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

        ObjectMapper mapper = new ObjectMapper();
        mapper.enable(SerializationFeature.INDENT_OUTPUT);

        // Top-level result object
        ObjectNode root = mapper.createObjectNode();
        ArrayNode experiments = mapper.createArrayNode();

        // --- Extract per-probe BMD results ---
        // Each BMDResult corresponds to one organ×sex experiment that went
        // through prefiltering → curve fitting → BMD calculation.
        List<BMDResult> bmdResults = project.getbMDResult();
        if (bmdResults == null) bmdResults = Collections.emptyList();

        // Build a map from experiment name → BMDResult for cross-referencing
        // with category analysis results later.
        Map<String, ObjectNode> expNodes = new LinkedHashMap<>();

        for (BMDResult bmdResult : bmdResults) {
            String name = bmdResult.getName();
            // BMDResult name is like "Liver_PFHxSAm_Male_No0_curvefitprefilter_nofoldfilter_BMD"
            // The experiment name is everything before "_curvefitprefilter" or "_BMD"
            DoseResponseExperiment dre = bmdResult.getDoseResponseExperiment();
            String expName = dre != null ? dre.getName() : name;

            // Parse organ and sex from experiment name.
            // Convention: {Organ}_{Compound}_{Sex}_{suffix}
            // e.g., "Liver_PFHxSAm_Male_No0"
            String[] parts = expName.split("_");
            String organ = parts.length > 0 ? parts[0] : "Unknown";
            // Sex is typically the third component — search for Male/Female
            String sex = "Unknown";
            for (String part : parts) {
                if (part.equalsIgnoreCase("Male")) { sex = "Male"; break; }
                if (part.equalsIgnoreCase("Female")) { sex = "Female"; break; }
            }

            int totalProbes = dre != null ? dre.getProbeResponses().size() : 0;

            ObjectNode expNode = mapper.createObjectNode();
            expNode.put("name", expName);
            expNode.put("organ", organ);
            expNode.put("sex", sex);
            expNode.put("total_probes", totalProbes);

            // Per-gene BMD results
            ArrayNode genesArray = mapper.createArrayNode();
            List<ProbeStatResult> probes = bmdResult.getProbeStatResults();
            if (probes != null) {
                for (ProbeStatResult psr : probes) {
                    ObjectNode gene = mapper.createObjectNode();

                    // Probe ID is like "ACAA1A_7954" (symbol_entrezId)
                    String probeId = psr.getProbeResponse().getProbe().getId();
                    gene.put("probe_id", probeId);

                    // Extract gene symbol: everything before the last underscore+digits
                    // "ACAA1A_7954" → "Acaa1a", "CYP2B1_24300" → "Cyp2b1"
                    String symbol = probeId;
                    int lastUnderscore = probeId.lastIndexOf('_');
                    if (lastUnderscore > 0) {
                        String suffix = probeId.substring(lastUnderscore + 1);
                        // Check if suffix is purely numeric (Entrez ID)
                        if (suffix.matches("\\d+")) {
                            symbol = probeId.substring(0, lastUnderscore);
                        }
                    }
                    gene.put("gene_symbol", symbol);

                    StatResult best = psr.getBestStatResult();
                    if (best != null) {
                        gene.put("bmd", best.getBMD());
                        gene.put("bmdl", best.getBMDL());
                        gene.put("bmdu", best.getBMDU());

                        // Direction: 1 = up, -1 = down
                        short dir = best.getAdverseDirection();
                        gene.put("direction", dir > 0 ? "up" : dir < 0 ? "down" : "none");

                        gene.put("r_squared", best.getrSquared());

                        gene.put("fold_change", best.getFoldChangeToTop());
                        gene.put("fit_p_value", best.getFitPValue());
                    }

                    genesArray.add(gene);
                }
            }
            expNode.set("genes", genesArray);

            // Placeholder for GO BP — will be filled from category analysis
            expNode.set("go_bp", mapper.createArrayNode());

            expNodes.put(expName, expNode);
        }

        // --- Extract GO Biological Process category results ---
        // Category analysis results are grouped by analysis run.  Each run's
        // name encodes the experiment + category type (GO_BP, GENE, DEFINED).
        // We only want GO_BP for the report's gene set analysis.
        List<CategoryAnalysisResults> catResultSets = project.getCategoryAnalysisResults();
        if (catResultSets == null) catResultSets = Collections.emptyList();

        for (CategoryAnalysisResults catResults : catResultSets) {
            String catName = catResults.getName();

            // Only process GO Biological Process analyses
            if (!catName.contains("GO_BP")) continue;

            // Find the experiment this belongs to.
            // Category name starts with the experiment name, e.g.:
            //   "Liver_PFHxSAm_Male_No0_curvefitprefilter_nofoldfilter_BMD_S1500_Plus_Rat_GO_BP_..."
            // Match against known experiment names.
            String matchedExp = null;
            for (String expName : expNodes.keySet()) {
                if (catName.startsWith(expName)) {
                    matchedExp = expName;
                    break;
                }
            }
            if (matchedExp == null) {
                System.err.println("  WARNING: Could not match category result to experiment: " + catName);
                continue;
            }

            ObjectNode expNode = expNodes.get(matchedExp);
            ArrayNode goBpArray = (ArrayNode) expNode.get("go_bp");

            // The typo "categoryAnalsyisResults" is in BMDExpress's own code —
            // the getter method is getCategoryAnalsyisResults() (sic).
            @SuppressWarnings("deprecation")
            List<CategoryAnalysisResult> results = catResults.getCategoryAnalsyisResults();
            if (results == null) continue;

            for (CategoryAnalysisResult car : results) {
                // Only include categories with genes that passed all filters
                Integer passed = car.getGenesThatPassedAllFilters();
                if (passed == null || passed == 0) continue;

                ObjectNode goEntry = mapper.createObjectNode();

                CategoryIdentifier ci = car.getCategoryIdentifier();
                goEntry.put("go_id", ci.getId());
                goEntry.put("go_term", ci.getTitle());
                if (ci instanceof GOCategoryIdentifier) {
                    String level = ((GOCategoryIdentifier) ci).getGoLevel();
                    if (level != null) goEntry.put("go_level", Integer.parseInt(level));
                }

                // BMD statistics — full stat blocks so the UI can display
                // whichever aggregate the user selects (mean, median, 5th pct, etc.)
                // Use the *TotalGenes variants for 5th/10th percentile —
                // the short-named getters (getBmdFifthPercentile etc.) are
                // transient fields that are null after Java deserialization.
                // The TotalGenes variants are the persisted fields with data.
                goEntry.set("bmd_stats", buildStatBlock(mapper,
                    car.getBmdMean(), car.getBmdMedian(), car.getBmdMinimum(),
                    car.getBmdWMean(), car.getBmdSD(), car.getBmdWSD(),
                    car.getBmdFifthPercentileTotalGenes(), car.getBmdTenthPercentileTotalGenes(),
                    car.getbmdLower95(), car.getbmdUpper95()));
                goEntry.set("bmdl_stats", buildStatBlock(mapper,
                    car.getBmdlMean(), car.getBmdlMedian(), car.getBmdlMinimum(),
                    car.getBmdlWMean(), car.getBmdlSD(), car.getBmdlWSD(),
                    car.getBmdlFifthPercentileTotalGenes(), car.getBmdlTenthPercentileTotalGenes(),
                    car.getbmdlLower95(), car.getbmdlUpper95()));
                goEntry.set("bmdu_stats", buildStatBlock(mapper,
                    car.getBmduMean(), car.getBmduMedian(), car.getBmduMinimum(),
                    car.getBmduWMean(), car.getBmduSD(), car.getBmduWSD(),
                    car.getBmduFifthPercentileTotalGenes(), car.getBmduTenthPercentileTotalGenes(),
                    car.getbmduLower95(), car.getbmduUpper95()));

                // Legacy fields for backward compatibility
                Double bmdMedian = car.getBmdMedian();
                Double bmdlMedian = car.getBmdlMedian();
                Double bmduMedian = car.getBmduMedian();
                if (bmdMedian != null) goEntry.put("bmd_median", bmdMedian);
                if (bmdlMedian != null) goEntry.put("bmdl_median", bmdlMedian);
                if (bmduMedian != null) goEntry.put("bmdu_median", bmduMedian);

                // Gene counts
                Integer allCount = car.getGeneAllCount();
                if (allCount != null) goEntry.put("n_genes", allCount);
                goEntry.put("n_passed", passed);

                // Direction
                // getOverallDirection() returns an enum — UP, DOWN, or CONFLICT/null
                try {
                    Object dir = car.getOverallDirection();
                    if (dir != null) {
                        String dirStr = dir.toString().toLowerCase();
                        goEntry.put("direction", dirStr);
                    }
                } catch (Exception e) {
                    // Direction not available
                }

                // Fisher's exact p-value (two-tail, for enrichment significance)
                Double fishers = car.getFishersExactTwoTailPValue();
                if (fishers != null) goEntry.put("fishers_two_tail", fishers);

                // Gene symbols (semicolon-separated string from BMDExpress)
                String symbols = car.getGeneSymbols();
                if (symbols != null) goEntry.put("gene_symbols", symbols);

                goBpArray.add(goEntry);
            }
        }

        // Assemble final output
        for (ObjectNode expNode : expNodes.values()) {
            experiments.add(expNode);
        }
        root.set("experiments", experiments);

        // Write output
        System.err.println("  Writing genomics JSON to " + jsonOut + "...");
        mapper.writeValue(new File(jsonOut), root);
        System.err.println("  Done. " + expNodes.size() + " experiments exported.");
    }

    /**
     * Build a JSON object containing all BMD aggregate statistics for one
     * metric (BMD, BMDL, or BMDU).  Mirrors ExportCategories.buildStatBlock().
     */
    private static ObjectNode buildStatBlock(
            ObjectMapper mapper,
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
}
