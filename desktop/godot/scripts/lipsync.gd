extends Node

class_name FrequencyAnalyzer

var fft_size := 256
var silence_threshold := 0.015
var smoothing_factor := 0.35
var hold_frames := 2
var intensity_smoothing := 0.2
var energy_smoothing := 0.5

var _current_viseme := "sil"
var _current_intensity := 0.0
var _previous_viseme := "sil"
var _transition_progress := 1.0
var _hold_counter := 0

var _smoothed_amplitude := 0.0
var _smoothed_bands := {
	"sub": 0.0, "low": 0.0, "mid": 0.0, "high": 0.0, "veryHigh": 0.0
}

var _sample_rate := 44100.0
var _effect: AudioEffectCapture = null


func start(bus_name: String = "Master"):
	var bus_idx = AudioServer.get_bus_index(bus_name)
	_effect = AudioEffectCapture.new()
	AudioServer.add_bus_effect(bus_idx, _effect, 0)
	_effect.clear_buffer()
	reset()


func stop():
	if _effect != null:
		_effect.clear_buffer()
		_effect = null


func reset():
	_current_viseme = "sil"
	_current_intensity = 0.0
	_previous_viseme = "sil"
	_transition_progress = 1.0
	_hold_counter = 0
	_smoothed_amplitude = 0.0
	for k in _smoothed_bands:
		_smoothed_bands[k] = 0.0


func analyze() -> Dictionary:
	if _effect == null or _effect.get_frames_available() == 0:
		return _make_frame("sil", 0.0)

	var stereo = _effect.get_buffer(_effect.get_frames_available())
	_effect.clear_buffer()
	var mono = _stereo_to_mono(stereo)

	var mags = _compute_fft_magnitudes(mono)

	var raw_amplitude = AudioUtils.calculate_rms(mono)
	_smoothed_amplitude = AudioUtils.smooth_value(_smoothed_amplitude, raw_amplitude, smoothing_factor)

	var raw_bands = AudioUtils.extract_band_energies(mags, _sample_rate)
	for k in raw_bands:
		_smoothed_bands[k] = AudioUtils.smooth_value(_smoothed_bands[k], raw_bands[k], smoothing_factor)

	if _smoothed_amplitude < silence_threshold:
		_current_intensity = 0.0
		_current_viseme = "sil"
		_transition_progress = 1.0
		return _make_frame("sil", 0.0)

	var classification = _classify_viseme()
	var new_viseme = classification["viseme"]
	var confidence = classification["confidence"]

	if new_viseme != _current_viseme:
		_hold_counter += 1
		if _hold_counter >= hold_frames:
			_previous_viseme = _current_viseme
			_current_viseme = new_viseme
			_transition_progress = 0.0
			_hold_counter = 0
	else:
		_hold_counter = 0

	_current_intensity = AudioUtils.smooth_value(_current_intensity, confidence, intensity_smoothing)
	return _emit_viseme()


func _make_frame(viseme: String, intensity: float) -> Dictionary:
	var shape = Visemes.VISEME_SHAPES.get(viseme, Visemes.VISEME_SHAPES["sil"])
	return {
		"viseme": viseme,
		"intensity": intensity,
		"shape": {"open": shape["open"], "width": shape["width"], "round": shape["round"]},
		"transition": {"from": viseme, "to": viseme, "progress": 1.0}
	}


func _emit_viseme() -> Dictionary:
	var weight = Visemes.get_transition_weight(_previous_viseme, _current_viseme)
	_transition_progress = min(1.0, _transition_progress + (1.0 - weight) * 0.3)

	var shape: Dictionary
	if _transition_progress >= 1.0:
		var s = Visemes.VISEME_SHAPES.get(_current_viseme, Visemes.VISEME_SHAPES["sil"])
		shape = {"open": s["open"], "width": s["width"], "round": s["round"]}
	else:
		shape = Visemes.interpolate_shapes(_previous_viseme, _current_viseme, _transition_progress)

	return {
		"viseme": _current_viseme,
		"intensity": _current_intensity,
		"shape": shape,
		"transition": {"from": _previous_viseme, "to": _current_viseme, "progress": _transition_progress}
	}


func _classify_viseme() -> Dictionary:
	var bands = _smoothed_bands
	var amp = _smoothed_amplitude

	var sibilant_score = bands["high"] + bands["veryHigh"]
	var fricative_score = (bands["mid"] + bands["high"]) * 0.5

	if sibilant_score > 0.55 and bands["veryHigh"] > 0.3:
		var is_ch = bands["mid"] > bands["high"] and bands["sub"] > 0.15
		return {"viseme": "CH" if is_ch else "SS", "confidence": sibilant_score}

	if fricative_score > 0.5 and bands["low"] < 0.15:
		return {"viseme": "FF", "confidence": fricative_score}

	if amp > 0.6:
		var flatness = bands["sub"] * bands["low"] * bands["mid"]
		if flatness > 0.7:
			var is_plosive = bands["sub"] < 0.1 and bands["mid"] > 0.3
			if is_plosive:
				return {"viseme": "PP", "confidence": amp}
			return {"viseme": "DD", "confidence": amp}

	if bands["sub"] > 0.2 and bands["low"] > 0.2 and bands["high"] < 0.1:
		return {"viseme": "nn", "confidence": (bands["sub"] + bands["low"]) * 0.5}

	var vowel_score = bands["low"] + bands["mid"]
	if vowel_score > 0.4:
		var formant_ratio = bands["low"] / max(bands["mid"], 0.001)
		if formant_ratio > 1.5:
			return {"viseme": "aa", "confidence": vowel_score}
		elif formant_ratio > 0.8:
			if bands["sub"] > 0.15:
				return {"viseme": "O", "confidence": vowel_score}
			return {"viseme": "I", "confidence": vowel_score}
		else:
			return {"viseme": "E", "confidence": vowel_score}

	if amp > 0.4:
		return {"viseme": "aa", "confidence": amp * 0.6}

	return {"viseme": "sil", "confidence": 0.0}


func _stereo_to_mono(stereo: PackedVector2Array) -> PackedFloat32Array:
	var mono = PackedFloat32Array()
	mono.resize(stereo.size())
	for i in mono.size():
		mono[i] = (stereo[i].x + stereo[i].y) * 0.5
	return mono


func _compute_fft_magnitudes(samples: PackedFloat32Array) -> PackedFloat32Array:
	var s = samples
	if s.size() < fft_size:
		var padded = PackedFloat32Array()
		padded.resize(fft_size)
		for i in s.size():
			padded[i] = s[i]
		s = padded
	elif s.size() > fft_size:
		var sliced = PackedFloat32Array()
		sliced.resize(fft_size)
		var offset = s.size() - fft_size
		for i in fft_size:
			sliced[i] = s[offset + i]
		s = sliced

	var windowed = PackedFloat32Array()
	windowed.resize(fft_size)
	for i in fft_size:
		var hann = 0.5 * (1.0 - cos(2.0 * PI * i / float(fft_size - 1)))
		windowed[i] = s[i] * hann

	var real = windowed.duplicate()
	var imag = PackedFloat32Array()
	imag.resize(fft_size)

	_fft(real, imag)

	var bin_count = fft_size / 2 + 1
	var mags = PackedFloat32Array()
	mags.resize(bin_count)
	mags[0] = abs(real[0]) / float(fft_size)
	for i in range(1, bin_count - 1):
		mags[i] = sqrt(real[i] * real[i] + imag[i] * imag[i]) / float(fft_size)
	if bin_count > 1:
		mags[bin_count - 1] = abs(real[bin_count - 1]) / float(fft_size)
	return mags


func _fft(real: PackedFloat32Array, imag: PackedFloat32Array):
	var n = real.size()
	var bits = int(round(log(n) / log(2.0)))
	for i in n:
		var j = _bit_reverse(i, bits)
		if j > i:
			var tmp_r = real[i]
			var tmp_i = imag[i]
			real[i] = real[j]
			imag[i] = imag[j]
			real[j] = tmp_r
			imag[j] = tmp_i

	var step = 1
	while step < n:
		var half_step = step
		step <<= 1
		var angle_step = -PI / half_step
		for i in range(0, n, step):
			for k in half_step:
				var theta = angle_step * k
				var wr = cos(theta)
				var wi = sin(theta)
				var idx = i + k
				var jdx = idx + half_step
				var tr = wr * real[jdx] - wi * imag[jdx]
				var ti = wr * imag[jdx] + wi * real[jdx]
				real[jdx] = real[idx] - tr
				imag[jdx] = imag[idx] - ti
				real[idx] += tr
				imag[idx] += ti


func _bit_reverse(x: int, bits: int) -> int:
	var result = 0
	for i in bits:
		result = (result << 1) | (x & 1)
		x >>= 1
	return result
