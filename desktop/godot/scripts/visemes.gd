extends Node

const EXTENDED_VISEMES = {
	"sil": {"label": "Silence", "desc": "Mouth closed, neutral"},
	"PP": {"label": "P, B, M", "desc": "Lips pressed together"},
	"FF": {"label": "F, V", "desc": "Lower lip touching upper teeth"},
	"TH": {"label": "TH", "desc": "Tongue between teeth"},
	"DD": {"label": "D, T, N, L", "desc": "Tongue behind upper teeth"},
	"kk": {"label": "K, G, NG", "desc": "Back of tongue raised"},
	"CH": {"label": "CH, J, SH", "desc": "Teeth together, lips rounded"},
	"SS": {"label": "S, Z", "desc": "Teeth nearly together"},
	"nn": {"label": "N (continuant)", "desc": "Soft palate open, nasal"},
	"RR": {"label": "R", "desc": "Tongue curled back"},
	"aa": {"label": "father, palm", "desc": "Mouth open, tongue low"},
	"E": {"label": "bed, dress", "desc": "Mouth mid-open, lips spread"},
	"I": {"label": "sit, kit", "desc": "Mouth slightly open, lips spread"},
	"O": {"label": "thought, lot", "desc": "Mouth mid-open, lips rounded"},
	"U": {"label": "foot, good", "desc": "Mouth slightly open, lips very rounded"}
}

const EXTENDED_KEYS = ["sil", "PP", "FF", "TH", "DD", "kk", "CH", "SS", "nn", "RR", "aa", "E", "I", "O", "U"]

const SIMPLE_VISEMES = {
	"A": {"desc": "aa, E", "extended": ["aa", "E"]},
	"B": {"desc": "PP", "extended": ["PP"]},
	"C": {"desc": "I, SS, RR", "extended": ["I", "SS", "RR"]},
	"D": {"desc": "O", "extended": ["O"]},
	"E": {"desc": "U", "extended": ["U"]},
	"F": {"desc": "FF, TH, DD, kk, CH, nn", "extended": ["FF", "TH", "DD", "kk", "CH", "nn"]}
}

const EXTENDED_TO_SIMPLE = {
	"aa": "A", "E": "A",
	"PP": "B",
	"I": "C", "SS": "C", "RR": "C",
	"O": "D",
	"U": "E",
	"FF": "F", "TH": "F", "DD": "F", "kk": "F", "CH": "F", "nn": "F",
	"sil": "A"
}

const PHONEME_TO_VISEME = {
	"AA": "aa", "AE": "aa", "AH": "aa",
	"AO": "O", "AW": "O", "AY": "I",
	"B": "PP", "CH": "CH", "D": "DD", "DH": "DD",
	"EH": "E", "ER": "RR", "EY": "I",
	"F": "FF", "G": "kk", "HH": "kk",
	"IH": "I", "IY": "I",
	"JH": "CH",
	"K": "kk",
	"L": "DD", "M": "PP", "N": "nn", "NG": "kk",
	"OW": "O", "OY": "I",
	"P": "PP", "R": "RR",
	"S": "SS", "SH": "CH", "T": "DD", "TH": "TH",
	"UH": "U", "UW": "U",
	"V": "FF", "W": "U", "Y": "I", "Z": "SS", "ZH": "CH"
}

const TRANSITION_WEIGHTS = {
	"sil_aa": 0.3, "aa_O": 0.6,
	"PP_FF": 0.4, "FF_PP": 0.4,
	"aa_I": 0.5, "I_aa": 0.5
}

const DEFAULT_TRANSITION_WEIGHT = 0.35

const VISEME_SHAPES = {
	"sil": {"open": 0.0, "width": 0.5, "round": 0.0},
	"PP": {"open": 0.0, "width": 0.5, "round": 0.0},
	"FF": {"open": 0.1, "width": 0.4, "round": 0.0},
	"TH": {"open": 0.2, "width": 0.5, "round": 0.0},
	"DD": {"open": 0.3, "width": 0.6, "round": 0.0},
	"kk": {"open": 0.4, "width": 0.6, "round": 0.0},
	"CH": {"open": 0.3, "width": 0.5, "round": 0.6},
	"SS": {"open": 0.1, "width": 0.7, "round": 0.0},
	"nn": {"open": 0.4, "width": 0.5, "round": 0.0},
	"RR": {"open": 0.2, "width": 0.4, "round": 0.4},
	"aa": {"open": 0.9, "width": 0.6, "round": 0.0},
	"E": {"open": 0.5, "width": 0.7, "round": 0.0},
	"I": {"open": 0.3, "width": 0.8, "round": 0.0},
	"O": {"open": 0.5, "width": 0.4, "round": 0.8},
	"U": {"open": 0.2, "width": 0.3, "round": 0.9}
}

static func get_transition_weight(from_viseme: String, to_viseme: String) -> float:
	var key = from_viseme + "_" + to_viseme
	if TRANSITION_WEIGHTS.has(key):
		return TRANSITION_WEIGHTS[key]
	return DEFAULT_TRANSITION_WEIGHT

static func interpolate_shapes(from_key: String, to_key: String, t: float) -> Dictionary:
	var from_shape = VISEME_SHAPES.get(from_key, VISEME_SHAPES["sil"])
	var to_shape = VISEME_SHAPES.get(to_key, VISEME_SHAPES["sil"])
	var ct = clamp(t, 0.0, 1.0)
	return {
		"open": from_shape["open"] + (to_shape["open"] - from_shape["open"]) * ct,
		"width": from_shape["width"] + (to_shape["width"] - from_shape["width"]) * ct,
		"round": from_shape["round"] + (to_shape["round"] - from_shape["round"]) * ct
	}
