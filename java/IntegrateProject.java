/**
 * IntegrateProject — merge multiple data files into a single BMDProject JSON.
 *
 * Uses BMDExpress 3's native data model classes (via bmdx-core) for all
 * heavy lifting:
 *   - .bm2 merge:  ProjectUtilities.addProjectToProject() — the same code
 *                   BMDExpress's CLI "combine" command uses.
 *   - .txt/.csv:   ExperimentFileUtil.readFile() — native tab-delimited parser.
 *   - Serialization: Jackson ObjectMapper with NaN→null custom serializers
 *                   so the output is always valid JSON (BMDExpress's own
 *                   exportToJson() doesn't handle NaN).
 *
 * NTP xlsx files (long-format animal data) must be pre-converted to the
 * tab-delimited pivot format by the Python layer before being passed here.
 *
 * An optional metadata sidecar JSON provides ExperimentDescription fields
 * (species, sex, organ, test article, etc.) inferred by the LLM.  These
 * are applied to experiments by name match, respecting any metadata already
 * set in the .bm2 file (LLM metadata is a fallback, not an override).
 *
 * Usage:
 *   java -cp <classpath>:java/ IntegrateProject \
 *       --output integrated.json \
 *       --bm2 file1.bm2 file2.bm2 \
 *       --txt data1.txt data2.csv \
 *       --metadata metadata_sidecar.json
 *
 * All flags are optional except --output.  At least one --bm2 or --txt
 * file must be provided.
 *
 * Pre-compile:
 *   javac -cp <classpath> java/IntegrateProject.java -d java/
 */

import java.io.*;
import java.util.*;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.fasterxml.jackson.core.JsonGenerator;
import com.fasterxml.jackson.databind.JsonSerializer;
import com.fasterxml.jackson.databind.SerializerProvider;
import com.fasterxml.jackson.databind.module.SimpleModule;
import com.sciome.bmdexpress2.mvp.model.BMDProject;
import com.sciome.bmdexpress2.mvp.model.DoseResponseExperiment;
import com.sciome.bmdexpress2.mvp.model.info.ExperimentDescription;
import com.sciome.bmdexpress2.mvp.model.info.TestArticleIdentifier;
import com.sciome.bmdexpress2.util.ExperimentFileUtil;
import com.sciome.bmdexpress2.util.ProjectUtilities;

public class IntegrateProject {

    public static void main(String[] args) throws Exception {
        // --- Parse command-line arguments ---
        String outputPath = null;
        List<String> bm2Paths = new ArrayList<>();
        List<String> txtPaths = new ArrayList<>();
        String metadataPath = null;

        for (int i = 0; i < args.length; i++) {
            switch (args[i]) {
                case "--output":
                    outputPath = args[++i];
                    break;
                case "--bm2":
                    while (i + 1 < args.length && !args[i + 1].startsWith("--")) {
                        bm2Paths.add(args[++i]);
                    }
                    break;
                case "--txt":
                    while (i + 1 < args.length && !args[i + 1].startsWith("--")) {
                        txtPaths.add(args[++i]);
                    }
                    break;
                case "--metadata":
                    metadataPath = args[++i];
                    break;
                default:
                    System.err.println("Unknown argument: " + args[i]);
                    printUsage();
                    System.exit(1);
            }
        }

        if (outputPath == null) {
            System.err.println("Error: --output is required");
            printUsage();
            System.exit(1);
        }
        if (bm2Paths.isEmpty() && txtPaths.isEmpty()) {
            System.err.println("Error: at least one --bm2 or --txt file is required");
            printUsage();
            System.exit(1);
        }

        // --- Create the unified BMDProject ---
        BMDProject unified = new BMDProject();
        unified.setName("integrated");

        // --- Load and merge .bm2 files ---
        // Uses BMDExpress's native ProjectUtilities.addProjectToProject() —
        // the same code the CLI "combine" command uses.  Handles unique naming,
        // merges all result types (experiments, prefilters, BMD, category).
        for (String bm2Path : bm2Paths) {
            System.out.println("  Loading .bm2: " + bm2Path);
            BMDProject source;
            try (FileInputStream fis = new FileInputStream(new File(bm2Path));
                 BufferedInputStream bis = new BufferedInputStream(fis, 1024 * 2000);
                 ObjectInputStream ois = new ObjectInputStream(bis)) {
                source = (BMDProject) ois.readObject();
            }

            // Native merge — handles experiments, prefilters, BMD results,
            // category results, and unique naming in one call.
            ProjectUtilities.addProjectToProject(unified, source);

            System.out.println("    Merged: " +
                source.getDoseResponseExperiments().size() + " experiments, " +
                source.getbMDResult().size() + " BMD results, " +
                source.getCategoryAnalysisResults().size() + " category results");
        }

        // --- Load .txt/.csv files ---
        // BMDExpress's native importer handles header detection, dose parsing,
        // treatment sorting, and probe response construction.
        // ExperimentDescriptionParser also parses metadata from file headers.
        for (String txtPath : txtPaths) {
            System.out.println("  Loading .txt/.csv: " + txtPath);
            File txtFile = new File(txtPath);

            DoseResponseExperiment exp = ExperimentFileUtil.getInstance()
                .readFile(txtFile, true);

            if (exp == null) {
                System.err.println("    WARNING: Failed to parse " + txtPath + " — skipping");
                continue;
            }

            unified.getDoseResponseExperiments().add(exp);
            unified.giveBMDAnalysisUniqueName(exp, exp.getName());
            System.out.println("    Added experiment: " + exp.getName() +
                " (" + exp.getProbeResponses().size() + " probes)");
        }

        // --- Apply metadata sidecar ---
        // JSON object keyed by experiment name, each value containing
        // ExperimentDescription fields inferred by the LLM.  Only applied
        // to experiments that don't already have metadata (bm2-native
        // metadata takes precedence over LLM inference).
        if (metadataPath != null) {
            System.out.println("  Applying metadata sidecar: " + metadataPath);
            applyMetadataSidecar(unified, metadataPath);
        }

        // --- Serialize via Jackson ---
        System.out.println("  Writing unified project to " + outputPath + "...");
        ObjectMapper mapper = createNanSafeMapper();
        mapper.writeValue(new File(outputPath), unified);

        System.out.println("  Done: " +
            unified.getDoseResponseExperiments().size() + " experiments, " +
            unified.getbMDResult().size() + " BMD results, " +
            unified.getCategoryAnalysisResults().size() + " category results → " +
            outputPath);
    }

    /**
     * Create a Jackson ObjectMapper that writes NaN/Infinity as null.
     *
     * BMDExpress's data model uses Double.NaN extensively for missing BMD
     * values (getBMD(), getBMDL(), getBMDU() return NaN as default).
     * Jackson's default serializers emit bare NaN which is invalid JSON
     * and breaks client-side parsers like Oboe.js.
     *
     * This mapper registers custom Float/Double serializers that convert
     * NaN and Infinity to JSON null.  This is the ONLY place where NaN
     * handling is needed — the model classes are untouched.
     */
    public static ObjectMapper createNanSafeMapper() {
        ObjectMapper mapper = new ObjectMapper();
        mapper.enable(SerializationFeature.INDENT_OUTPUT);

        SimpleModule nanModule = new SimpleModule("NaN-to-null");
        nanModule.addSerializer(Float.class, new JsonSerializer<Float>() {
            @Override
            public void serialize(Float v, JsonGenerator gen, SerializerProvider sp)
                    throws IOException {
                if (v == null || v.isNaN() || v.isInfinite()) gen.writeNull();
                else gen.writeNumber(v);
            }
        });
        nanModule.addSerializer(Double.class, new JsonSerializer<Double>() {
            @Override
            public void serialize(Double v, JsonGenerator gen, SerializerProvider sp)
                    throws IOException {
                if (v == null || v.isNaN() || v.isInfinite()) gen.writeNull();
                else gen.writeNumber(v);
            }
        });
        mapper.registerModule(nanModule);

        return mapper;
    }

    /**
     * Apply LLM-inferred metadata from a sidecar JSON file to experiments
     * that don't already have metadata.
     */
    private static void applyMetadataSidecar(BMDProject project, String metadataPath)
            throws Exception {
        ObjectMapper reader = new ObjectMapper();
        JsonNode sidecar = reader.readTree(new File(metadataPath));

        int applied = 0;
        for (DoseResponseExperiment exp : project.getDoseResponseExperiments()) {
            // Skip experiments that already have meaningful metadata
            if (exp.getExperimentDescription().hasDescription()) {
                continue;
            }

            JsonNode meta = sidecar.get(exp.getName());
            if (meta == null) continue;

            ExperimentDescription desc = new ExperimentDescription();

            // Test article
            JsonNode ta = meta.get("testArticle");
            if (ta != null && !ta.isNull()) {
                TestArticleIdentifier tai = new TestArticleIdentifier(
                    textOrNull(ta, "name"),
                    textOrNull(ta, "casrn"),
                    textOrNull(ta, "dsstox")
                );
                desc.setTestArticle(tai);
            }

            // Structured fields — each maps directly to a setter
            setIfPresent(meta, "subjectType", desc::setSubjectType);
            setIfPresent(meta, "species",     desc::setSpecies);
            setIfPresent(meta, "strain",      desc::setStrain);
            setIfPresent(meta, "sex",         desc::setSex);
            setIfPresent(meta, "organ",       desc::setOrgan);
            setIfPresent(meta, "cellLine",    desc::setCellLine);
            setIfPresent(meta, "studyDuration", desc::setStudyDuration);
            setIfPresent(meta, "platform",    desc::setPlatform);
            setIfPresent(meta, "provider",    desc::setProvider);
            setIfPresent(meta, "articleRoute", desc::setArticleRoute);
            setIfPresent(meta, "articleVehicle", desc::setArticleVehicle);
            setIfPresent(meta, "administrationMeans", desc::setAdministrationMeans);
            setIfPresent(meta, "articleType", desc::setArticleType);
            setIfPresent(meta, "dataType",    desc::setDataType);

            exp.setExperimentDescription(desc);
            applied++;
        }
        System.out.println("    Applied metadata to " + applied + " experiments");
    }

    private static String textOrNull(JsonNode node, String field) {
        JsonNode child = node.get(field);
        return (child != null && !child.isNull()) ? child.asText() : null;
    }

    private static void setIfPresent(JsonNode node, String field,
                                      java.util.function.Consumer<String> setter) {
        JsonNode child = node.get(field);
        if (child != null && !child.isNull() && child.isTextual()) {
            setter.accept(child.asText());
        }
    }

    private static void printUsage() {
        System.err.println("Usage: IntegrateProject --output <path> " +
            "[--bm2 file1.bm2 ...] [--txt file1.txt ...] [--metadata sidecar.json]");
    }
}
