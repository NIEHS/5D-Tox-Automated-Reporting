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

import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sciome.bmdexpress2.mvp.model.BMDProject;

public class JsonToBm2 {

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

        System.out.println("  Reading JSON: " + jsonPath);
        BMDProject project = mapper.readValue(new File(jsonPath), BMDProject.class);

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
