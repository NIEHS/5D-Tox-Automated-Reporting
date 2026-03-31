/**
 * JsonToBm2 — Convert a Jackson-serialized BMDProject JSON back to .bm2 format.
 *
 * Closes the metadata loop: the webapp infers experiment metadata via LLM,
 * the user approves it, IntegrateProject applies it to the BMDProject JSON,
 * and this tool writes the enriched data back to the canonical .bm2 format
 * (Java ObjectOutputStream) that BMDExpress 3 can natively open.
 *
 * The round-trip works because:
 *   - IntegrateProject writes JSON with Jackson @type/@ref annotations, so
 *     Jackson can reconstruct the full polymorphic object graph.
 *   - ProbeResponse.setResponses() rebuilds the byte blob (responsesBlob)
 *     and float cache (responseArray) from the List<Float>, so the transient
 *     fields are correctly populated before ObjectOutputStream serialization.
 *   - ExperimentDescription is Serializable with a stable serialVersionUID,
 *     so any metadata fields survive the round-trip.
 *
 * The output .bm2 file is a standard BMDExpress 3 project file.  Opening it
 * in BMDExpress 3 will show the experiments with their metadata pre-filled
 * (species, sex, organ, test article, etc.) — no manual entry needed.
 *
 * Extra JSON keys added by the Python layer (_meta, _category_lookup) are
 * silently ignored via DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES=false.
 *
 * Usage:
 *   java -cp <classpath>:java/ JsonToBm2 integrated.json output.bm2
 *
 * Pre-compile:
 *   javac -cp <classpath> java/JsonToBm2.java -d java/
 */

import java.io.*;
import java.util.Iterator;

import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.DoubleNode;
import com.sciome.bmdexpress2.mvp.model.BMDProject;

public class JsonToBm2 {

    /**
     * Recursively walk a JSON tree and replace null entries inside
     * "responses" arrays with NaN.
     *
     * When the Python pivot writes "NaN" for missing animal measurements,
     * Jackson serializes it as JSON null (since JSON has no NaN literal).
     * On deserialization, ProbeResponse.setResponses(List<Float>) receives
     * a list containing Java null entries, and calling floatValue() on them
     * throws a NullPointerException.
     *
     * This pre-processing step converts nulls in "responses" arrays to the
     * JSON number NaN (which Jackson deserializes as Float.NaN), so the
     * setResponses() call succeeds.  The NaN values propagate through to
     * the .bm2 file where BMDExpress 3 treats them as missing data.
     */
    private static int sanitizeNulls(JsonNode node) {
        int replaced = 0;
        if (node.isObject()) {
            // If this object has a "responses" array, replace nulls with NaN
            JsonNode responses = node.get("responses");
            if (responses != null && responses.isArray()) {
                ArrayNode arr = (ArrayNode) responses;
                for (int i = 0; i < arr.size(); i++) {
                    if (arr.get(i).isNull()) {
                        arr.set(i, new DoubleNode(Double.NaN));
                        replaced++;
                    }
                }
            }
            // Recurse into all child fields
            Iterator<JsonNode> children = node.elements();
            while (children.hasNext()) {
                replaced += sanitizeNulls(children.next());
            }
        } else if (node.isArray()) {
            for (JsonNode child : node) {
                replaced += sanitizeNulls(child);
            }
        }
        return replaced;
    }

    public static void main(String[] args) throws Exception {
        if (args.length < 2) {
            System.err.println("Usage: JsonToBm2 <input.json> <output.bm2>");
            System.exit(1);
        }

        String jsonPath = args[0];
        String bm2Path = args[1];

        // --- Read JSON into BMDProject ---
        // FAIL_ON_UNKNOWN_PROPERTIES=false skips _meta, _category_lookup,
        // and any other Python-added keys that aren't part of the Java model.
        ObjectMapper mapper = new ObjectMapper();
        mapper.configure(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES, false);

        // Pre-process: read as tree first, replace null values in "responses"
        // arrays with NaN so ProbeResponse.setResponses() doesn't NPE.
        // This handles NaN values from the pivot (animals missing measurements
        // on certain study days, or animals that died before terminal sacrifice).
        System.out.println("  Reading JSON: " + jsonPath);
        JsonNode tree = mapper.readTree(new File(jsonPath));
        int nullsReplaced = sanitizeNulls(tree);
        if (nullsReplaced > 0) {
            System.out.println("  Sanitized " + nullsReplaced + " null→NaN in responses arrays");
        }

        BMDProject project = mapper.treeToValue(tree, BMDProject.class);

        System.out.println("  Deserialized: " +
            project.getDoseResponseExperiments().size() + " experiments, " +
            project.getbMDResult().size() + " BMD results, " +
            project.getCategoryAnalysisResults().size() + " category results");

        // --- Write .bm2 via ObjectOutputStream ---
        // This is the same serialization format BMDExpress 3 uses natively.
        // ProbeResponse.setResponses() (called by Jackson during deserialization)
        // already rebuilt responsesBlob from the List<Float>, so the byte blob
        // is ready for ObjectOutputStream.
        System.out.println("  Writing .bm2: " + bm2Path);
        try (FileOutputStream fos = new FileOutputStream(new File(bm2Path));
             BufferedOutputStream bos = new BufferedOutputStream(fos, 1024 * 2000);
             ObjectOutputStream oos = new ObjectOutputStream(bos)) {
            oos.writeObject(project);
        }

        // Verify file was written
        File output = new File(bm2Path);
        long sizeKB = output.length() / 1024;
        System.out.println("  Done: " + bm2Path + " (" + sizeKB + " KB)");
    }
}
