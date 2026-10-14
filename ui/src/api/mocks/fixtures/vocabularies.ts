import type { Vocabularies } from '../../types'

/**
 * GET /api/v2/vocabularies, mocked.
 *
 * Every list is copied from bmdx_pipe.VOCABULARIES (2026-10-14), and strain
 * depends on species as it does there. Two things are MOCK ONLY, pending the
 * backend:
 * - articleVehicle and administrationMeans depending on articleRoute: bmdx_pipe
 *   has no such map; the lists below are placeholders, not a rule.
 * - the id patterns: PROPOSED; the backend should serve its own.
 */
export const VOCABULARIES: Vocabularies = {
  "vocabularies": {
    "sex": {
      "label": "Sex",
      "values": [
        "male",
        "female",
        "both",
        "mixed",
        "NA"
      ]
    },
    "organ": {
      "label": "Organ",
      "values": [
        "adrenal",
        "bladder",
        "blood",
        "bone",
        "bone marrow",
        "brain",
        "cecum",
        "cervix",
        "colon",
        "duodenum",
        "epididymis",
        "esophagus",
        "eye",
        "gallbladder",
        "harderian gland",
        "heart",
        "ileum",
        "intestine",
        "jejunum",
        "kidney",
        "larynx",
        "liver",
        "lung",
        "lymph node",
        "mammary gland",
        "muscle",
        "nasal cavity",
        "nerve",
        "ovary",
        "oviduct",
        "pancreas",
        "parathyroid",
        "pituitary",
        "preputial gland",
        "prostate",
        "rectum",
        "salivary gland",
        "seminal vesicle",
        "skin",
        "spinal cord",
        "spleen",
        "sternum",
        "stomach",
        "testes",
        "thymus",
        "thyroid",
        "tongue",
        "trachea",
        "ureter",
        "uterus",
        "vagina",
        "Whole Body"
      ]
    },
    "species": {
      "label": "Species",
      "values": [
        "rat",
        "mouse",
        "human",
        "rabbit",
        "dog",
        "monkey",
        "zebrafish",
        "guinea pig",
        "hamster",
        "pig"
      ]
    },
    "strain": {
      "label": "Strain",
      "depends_on": "species",
      "by": {
        "rat": [
          "Sprague-Dawley",
          "Wistar",
          "Long-Evans",
          "Fischer 344",
          "Brown Norway"
        ],
        "mouse": [
          "C57BL/6",
          "BALB/c",
          "CD-1",
          "FVB/N",
          "129",
          "DBA/2",
          "NOD",
          "SCID",
          "B6C3F1",
          "B6D2F1"
        ]
      }
    },
    "platform": {
      "label": "Platform",
      "values": [
        "Body Weight",
        "Clinical Chemistry",
        "Hematology",
        "Hormones",
        "Organ Weight",
        "Tissue Concentration",
        "Clinical",
        "IVIVE",
        "Generic",
        "S1500+_rat",
        "S1500+_mouse",
        "S1500+_human",
        "Affymetrix Drosophila Genome Array",
        "Drosophila Genome 2.0 Array",
        "Human HG-Focus Target Array",
        "Human Genome U133A Array",
        "Human Genome U133 Plus 2.0 Array",
        "Human Genome U133A 2.0 Array",
        "HT HG-U133+ PM Array Plate",
        "HT MG-430 PM Array Plate",
        "HT RG-230 PM Array Plate",
        "Murine Genome U74A Array",
        "Murine Genome U74A Version 2 Array",
        "Mouse Expression 430A Array",
        "Mouse Expression 430B Array",
        "Mouse Genome 430A 2.0 Array",
        "Mouse Genome 430 2.0 Array",
        "Rat Expression 230A Array",
        "Rat Expression 230B Array",
        "Rat Genome 230 2.0 Array",
        "Rat Genome U34 Array",
        "Zebrafish Genome Array",
        "Agilent-021791 D. melanogaster (FruitFly) Oligo Microarray - V2",
        "Agilent-014850 Whole Human Genome Microarray 4x44K G4112F",
        "Agilent-014868 Whole Mouse Genome Microarray 4x44K G4122F",
        "Agilent-024196 Whole Rat Genome Microarray 4x44K",
        "Agilent-026437 D. rerio (Zebrafish) Oligo Microarray V3"
      ]
    },
    "provider": {
      "label": "Provider",
      "values": [
        "Affymetrix",
        "Agilent",
        "BioSpyder",
        "BMDExpress 3",
        "RefSeq",
        "Ensembl",
        "Apical",
        "Observations",
        "Generic"
      ]
    },
    "subjectType": {
      "label": "Kind of study",
      "values": [
        "in vivo",
        "in vitro",
        "in silico"
      ]
    },
    "articleRoute": {
      "label": "Route",
      "values": [
        "gavage",
        "oral",
        "inhaled",
        "transdermal"
      ]
    },
    "articleVehicle": {
      "label": "Vehicle",
      "depends_on": "articleRoute",
      "by": {
        "gavage": [
          "corn oil",
          "water"
        ],
        "oral": [
          "corn oil",
          "feed",
          "water"
        ],
        "inhaled": [
          "aerosol",
          "gas"
        ],
        "transdermal": []
      }
    },
    "administrationMeans": {
      "label": "Means of administration",
      "depends_on": "articleRoute",
      "by": {
        "gavage": [
          "gavage"
        ],
        "oral": [
          "gavage",
          "drinking water",
          "dietary"
        ],
        "inhaled": [
          "whole-body",
          "nose-only"
        ],
        "transdermal": []
      }
    },
    "studyDuration": {
      "label": "Duration",
      "values": [
        "5d",
        "28d",
        "3h",
        "6h",
        "9h",
        "24h",
        "1d",
        "3d",
        "7d",
        "14d"
      ]
    },
    "articleType": {
      "label": "Kind of test article",
      "values": [
        "chemical",
        "mixture",
        "electromagnetic radiation"
      ]
    },
    "dataType": {
      "label": "Kind of data",
      "values": [
        "tox_study",
        "inferred",
        "gene_expression"
      ]
    }
  },
  "patterns": {
    "dtxsid": {
      "pattern": "^DTXSID\\d+$",
      "example": "DTXSID50469320",
      "say": "A DTXSID is the letters DTXSID followed by digits, as on the EPA CompTox dashboard."
    },
    "casrn": {
      "pattern": "^\\d{2,7}-\\d{2}-\\d$",
      "example": "41997-13-1",
      "say": "A CAS number is three groups of digits joined by hyphens, the last a single check digit."
    },
    "doi": {
      "pattern": "^10\\.\\d{4,9}/\\S+$",
      "example": "10.22427/NIEHS-10",
      "say": "A DOI starts with 10. followed by a number, a slash and the rest."
    },
    "date": {
      "pattern": "^\\d{4}-\\d{2}-\\d{2}$",
      "example": "2026-10-14",
      "say": "Write the date as year-month-day, for example 2026-10-14."
    }
  }
}

