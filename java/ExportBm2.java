/**
 * ExportBm2 — unified .bm2 export helper (JSON + category TSV in one JVM).
 *
 * Reads a BMDExpress 3 .bm2 file (Java serialized BMDProject) and produces
 * both outputs in a single JVM launch:
 *
 *   1. Full BMDProject as JSON (via Jackson ObjectMapper)
 *   2. Category analysis results as TSV (via BMDExpress's own export services)
 *
 * This replaces the previous approach of:
 *   - javac ExportBm2Json.java         (JVM #1 — compile)
 *   - java  ExportBm2Json              (JVM #2 — JSON export)
 *   - java  BMDExpressCommandLine export (JVM #3 — category TSV)
 *
 * Now it's a single pre-compiled class:
 *   - java ExportBm2 input.bm2 output.json output.tsv
 *
 * Usage:
 *   java -cp <classpath>:java/ ExportBm2 <bm2_path> <json_out> <tsv_out>
 *
 * Arguments:
 *   bm2_path  — path to the .bm2 file
 *   json_out  — path for the JSON export (full BMDProject)
 *   tsv_out   — path for the category analysis TSV export
 *              (use "NONE" to skip TSV export)
 *
 * Pre-compile once:
 *   javac -cp <classpath> java/ExportBm2.java -d java/
 */

import java.io.*;
import java.util.*;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.sciome.bmdexpress2.mvp.model.BMDProject;
import com.sciome.bmdexpress2.mvp.model.BMDExpressAnalysisDataSet;
import com.sciome.bmdexpress2.mvp.model.category.CategoryAnalysisResults;
import com.sciome.bmdexpress2.service.DataCombinerService;
import com.sciome.bmdexpress2.service.ProjectNavigationService;
import com.sciome.bmdexpress2.mvp.model.CombinedDataSet;

public class ExportBm2 {
    public static void main(String[] args) throws Exception {
        if (args.length < 3) {
            System.err.println("Usage: ExportBm2 <bm2_path> <json_out> <tsv_out>");
            System.err.println("  Use 'NONE' for tsv_out to skip category export.");
            System.exit(1);
        }

        String bm2Path = args[0];
        String jsonOut = args[1];
        String tsvOut  = args[2];

        // --- Deserialize the .bm2 file (Java ObjectInputStream) ---
        // BMDExpress stores projects as serialized BMDProject objects.
        // The buffered input stream size matches BMDExpress's own code.
        System.out.println("  Loading BMDProject from " + bm2Path + "...");
        BMDProject project;
        try (FileInputStream fileIn = new FileInputStream(new File(bm2Path));
             BufferedInputStream bIn = new BufferedInputStream(fileIn, 1024 * 2000);
             ObjectInputStream in = new ObjectInputStream(bIn)) {
            project = (BMDProject) in.readObject();
        }

        // --- Export #1: Full BMDProject as JSON via Jackson ---
        System.out.println("  Writing JSON to " + jsonOut + "...");
        ObjectMapper mapper = new ObjectMapper();
        mapper.enable(SerializationFeature.INDENT_OUTPUT);
        mapper.writeValue(new File(jsonOut), project);

        // --- Export #2: Category analysis as TSV ---
        // Uses BMDExpress's own DataCombinerService + ProjectNavigationService
        // to produce the same TSV format as the CLI export command.
        if (!"NONE".equalsIgnoreCase(tsvOut)) {
            List<CategoryAnalysisResults> catResults = project.getCategoryAnalysisResults();
            if (catResults != null && !catResults.isEmpty()) {
                System.out.println("  Writing category TSV (" + catResults.size()
                                   + " result sets) to " + tsvOut + "...");

                // Combine all categorical result sets into a unified dataset
                // with aligned columns (same as the CLI does).
                DataCombinerService combiner = new DataCombinerService();
                List<BMDExpressAnalysisDataSet> datasets = new ArrayList<>(catResults);
                CombinedDataSet combined = combiner.combineBMDExpressAnalysisDataSets(datasets);

                // Write TSV using BMDExpress's built-in exporter
                ProjectNavigationService navService = new ProjectNavigationService();
                navService.exportBMDExpressAnalysisDataSet(combined,
                    new File(tsvOut), true /* includeAnalysisInfo */);
            } else {
                System.out.println("  No category analysis results found — skipping TSV.");
                // Write an empty file so the caller doesn't need to special-case
                try (FileWriter w = new FileWriter(tsvOut)) {
                    w.write("");
                }
            }
        }

        System.out.println("  Done.");
    }
}
