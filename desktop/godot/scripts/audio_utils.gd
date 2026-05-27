extends Node

static func int16_bytes_to_float32(bytes: PackedByteArray) -> PackedFloat32Array:
	var count = bytes.size() / 2
	var out = PackedFloat32Array()
	out.resize(count)
	for i in count:
		var lo = int(bytes[i * 2])
		var hi = int(bytes[i * 2 + 1])
		var val = lo | (hi << 8)
		if val >= 32768:
			val -= 65536
		out[i] = float(val) / 32768.0
	return out

static func float32_to_int16_bytes(samples: PackedFloat32Array) -> PackedByteArray:
	var out = PackedByteArray()
	out.resize(samples.size() * 2)
	for i in samples.size():
		var v = clamp(samples[i], -1.0, 1.0)
		var int_val = int(round(v * 32767.0))
		if int_val < 0:
			int_val += 65536
		out.encode_s16(i * 2, int_val)
	return out

static func calculate_rms(samples: PackedFloat32Array) -> float:
	if samples.is_empty(): return 0.0
	var sum = 0.0
	for s in samples:
		sum += s * s
	return sqrt(sum / samples.size())

static func zero_crossing_rate(samples: PackedFloat32Array) -> float:
	if samples.size() < 2: return 0.0
	var count = 0
	for i in range(1, samples.size()):
		if (samples[i-1] >= 0.0 and samples[i] < 0.0) or (samples[i-1] < 0.0 and samples[i] >= 0.0):
			count += 1
	return float(count) / float(samples.size() - 1)

static func extract_band_energies(magnitudes: PackedFloat32Array, sample_rate: float) -> Dictionary:
	var bands = {
		"sub": [20.0, 200.0],
		"low": [200.0, 800.0],
		"mid": [800.0, 2500.0],
		"high": [2500.0, 5500.0],
		"veryHigh": [5500.0, 12000.0]
	}
	var result = {}
	var bin_count = magnitudes.size()
	var nyquist = sample_rate / 2.0
	for band_name in bands:
		var range_arr = bands[band_name] as Array
		var lo = range_arr[0] as float
		var hi = range_arr[1] as float
		var lo_bin = max(0, int(floor(lo / nyquist * bin_count)))
		var hi_bin = min(bin_count - 1, int(ceil(hi / nyquist * bin_count)))
		var energy = 0.0
		var count = 0
		for b in range(lo_bin, hi_bin + 1):
			energy += magnitudes[b]
			count += 1
		result[band_name] = energy / float(count) if count > 0 else 0.0
	return result

static func smooth_value(current: float, target: float, factor: float) -> float:
	return current + (target - current) * (1.0 - factor)

static func lerp_value(a: float, b: float, t: float) -> float:
	var ct = clamp(t, 0.0, 1.0)
	return a + (b - a) * ct
