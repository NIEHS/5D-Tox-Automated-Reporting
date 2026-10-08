/**
 * SubsetBm2 — keep only the experiments of one study in a BMDExpress project.
 *
 * NIEHS-07 … 10 publish ONE shared BMDExpress project holding four chemicals'
 * experiments (Kidney_PFHxSAm_Male, Liver_6-1 FTOH_Female, …).  A report built
 * from it must see only its own chemical's experiments.  This loads the .bm2,
 * keeps every experiment whose name contains the token (case-insensitive), drops
 * every analysis (prefilters, BMD results, category analyses) of an experiment
 * it does not keep, and writes the result as a standard .bm2.  Working on the
 * Java object graph keeps shared objects (chip, probes, annotations) intact,
 * which a JSON edit of the @ref-encoded export cannot guarantee.
 *
 * Usage:
 *   java -cp <classpath> SubsetBm2 input.bm2 output.bm2 TOKEN
 */

import java.io.*;
import java.util.*;

import com.sciome.bmdexpress2.mvp.model.BMDProject;
import com.sciome.bmdexpress2.mvp.model.DoseResponseExperiment;
import com.sciome.bmdexpress2.mvp.model.category.CategoryAnalysisResults;
import com.sciome.bmdexpress2.mvp.model.prefilter.PrefilterResults;
import com.sciome.bmdexpress2.mvp.model.stat.BMDResult;

public class SubsetBm2 {

    private static <T> int keepOnly(List<T> items, java.util.function.Predicate<T> keep) {
        int before = items.size();
        items.removeIf(keep.negate());
        return before - items.size();
    }

    public static void main(String[] args) throws Exception {
        if (args.length != 3) {
            System.err.println("usage: SubsetBm2 input.bm2 output.bm2 TOKEN");
            System.exit(2);
        }
        String token = args[2].toLowerCase(Locale.ROOT);
        BMDProject project;
        try (ObjectInputStream ois = new ObjectInputStream(
                new BufferedInputStream(new FileInputStream(args[0]), 1 << 20))) {
            project = (BMDProject) ois.readObject();
        }

        Set<DoseResponseExperiment> kept = Collections.newSetFromMap(new IdentityHashMap<>());
        for (DoseResponseExperiment exp : project.getDoseResponseExperiments()) {
            if (exp.getName() != null && exp.getName().toLowerCase(Locale.ROOT).contains(token)) {
                kept.add(exp);
            }
        }
        if (kept.isEmpty()) {
            System.err.println("SubsetBm2: no experiment name contains '" + args[2] + "'");
            System.exit(1);
        }
        int dropped = keepOnly(project.getDoseResponseExperiments(), kept::contains);
        java.util.function.Predicate<PrefilterResults> pre =
                r -> kept.contains(r.getDoseResponseExperiement());
        keepOnly(project.getOneWayANOVAResults(), r -> pre.test(r));
        keepOnly(project.getWilliamsTrendResults(), r -> pre.test(r));
        keepOnly(project.getCurveFitPrefilterResults(), r -> pre.test(r));
        keepOnly(project.getOriogenResults(), r -> pre.test(r));
        keepOnly(project.getbMDResult(), (BMDResult r) -> kept.contains(r.getDoseResponseExperiment()));
        keepOnly(project.getCategoryAnalysisResults(),
                (CategoryAnalysisResults r) -> kept.contains(r.getDoseResponseExperiment()));

        try (ObjectOutputStream oos = new ObjectOutputStream(
                new BufferedOutputStream(new FileOutputStream(args[1]), 1 << 20))) {
            oos.writeObject(project);
        }
        System.out.println("SubsetBm2: kept " + kept.size() + " experiment(s), dropped " + dropped
                + "; " + project.getbMDResult().size() + " BMD result(s), "
                + project.getCategoryAnalysisResults().size() + " category result(s)");
    }
}
