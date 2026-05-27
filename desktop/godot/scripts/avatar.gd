extends Node3D

class_name AvatarController

signal head_position_changed(x: float, y: float, visible: bool)

const BLINK_CLOSE_MAX := 0.12
const BLINK_OPEN_MAX := 5.0
const SACCADE_MIN_INTERVAL := 0.5
const SACCADE_PROC := 0.05
const SACCADE_RADIUS := deg_to_rad(5.0)
const SACCADE_SMOOTH_FACTOR := 4.0
const EXPRESSION_BLEND_RATE := 5.0
const LIP_SYNC_SCALE_NEUTRAL := 1.0
const LIP_SYNC_SCALE_EMOTIVE := 0.6

const EMOTION_TO_EXPRESSION = {
	"neutral": null,
	"happy": "happy", "cheerful": "happy", "amused": "happy",
	"laughing": "happy", "excited": "happy", "grateful": "happy",
	"sad": "sad", "tired": "sad", "bored": "sad",
	"embarrassed": "angry", "suspicious": "angry",
	"angry": "angry", "annoyed": "angry",
	"surprised": "surprised", "confused": "surprised",
	"curious": "relaxed", "admiration": "relaxed",
	"optimistic": "relaxed", "caring": "relaxed",
	"love": "relaxed", "thinking": "relaxed",
	"awed": "surprised", "fear": "surprised",
	"sleepy": "relaxed"
}

const EXPRESSION_NAMES := ["happy", "angry", "sad", "relaxed", "surprised"]

const IDLE_MICRO_ANIMS := [
	"curiosity", "amusement", "admiration",
	"optimism", "relief", "realization", "confusion"
]

var vrm_scene: Node3D = null
var _mesh_instances: Array[MeshInstance3D] = []
var _blend_shape_map: Dictionary = {}
var _blink_timer := 0.0
var _blink_value := 0.0
var _blink_enabled := true
var _saccade_target: Vector3 = Vector3.ZERO
var _saccade_current: Vector3 = Vector3.ZERO
var _saccade_timer := 0.0
var _expression_targets: Dictionary = {}
var _current_emotion := "neutral"
var _lip_sync_active := false
var _frequency_analyzer: FrequencyAnalyzer = null
var _idle_timer: Timer = null
var _tts_active := false
var _head_bone: Node3D = null
var _hips_bone: Node3D = null
var _hit_areas: HitAreaController = null
var _animation_player: AnimationPlayer = null
var _last_head_screen: Vector2 = Vector2.ZERO
var _camera: Camera3D = null
var _lip_scale := 1.0


func _ready():
	_camera = get_viewport().get_camera_3d()


func load_vrm(path: String):
	# For editor-imported VRM scenes, use the .scn file directly
	# For runtime-loaded VRM from backend, use GLTFDocument
	if path.begins_with("res://"):
		var scene = load(path)
		if scene == null:
			push_error("Failed to load VRM scene: ", path)
			return
		var instance = scene.instantiate()
		add_child(instance)
		vrm_scene = instance
	else:
		await _load_vrm_runtime(path)
	_setup_from_scene()


func _load_vrm_runtime(url: String):
	var http = HTTPRequest.new()
	add_child(http)
	http.request(url)
	var response = await http.request_completed
	http.queue_free()
	if response[0] != HTTPRequest.RESULT_SUCCESS:
		push_error("Failed to fetch VRM: ", url)
		return
	var body = response[3] as PackedByteArray
	var gltf = GLTFDocument.new()
	var state = GLTFState.new()
	state.handle_binary_image = GLTFState.HANDLE_BINARY_EMBED_AS_UNCOMPRESSED
	var err = gltf.append_from_buffer(body, "", state)
	if err != OK:
		push_error("GLTF parse error: ", err)
		return
	var scene = gltf.generate_scene(state)
	if scene == null:
		push_error("Failed to generate scene from VRM")
		return
	add_child(scene)
	vrm_scene = scene


func _setup_from_scene():
	_collect_mesh_instances(vrm_scene)
	_build_blend_shape_map()
	_find_bones()
	_setup_hit_areas()
	_setup_idle_behavior()
	_fit_camera()
	_load_idle_animation.call_deferred()


func _collect_mesh_instances(node: Node):
	if node is MeshInstance3D:
		_mesh_instances.append(node)
	for child in node.get_children():
		_collect_mesh_instances(child)


func _build_blend_shape_map():
	for mi in _mesh_instances:
		var mesh = mi.mesh
		if mesh == null or mesh.get_blend_shape_count() == 0:
			continue
		var idx = mi.get_surface_override_material_count()  # not blend shape count
		for i in mesh.get_blend_shape_count():
			var name = mesh.get_blend_shape_name(i).to_lower()
			_blend_shape_map[name] = {"mi": mi, "idx": i}


func _find_bones():
	if vrm_scene == null:
		return
	_head_bone = _find_node_named(vrm_scene, "head", true)
	if _head_bone == null:
		_head_bone = _find_bone_in_skeleton(vrm_scene, "Head")
	_hips_bone = _find_node_named(vrm_scene, "hips", true)
	if _hips_bone == null:
		_hips_bone = _find_bone_in_skeleton(vrm_scene, "Hips")
	_animation_player = vrm_scene.find_child("AnimationPlayer", true, false)
	if _animation_player == null:
		_animation_player = vrm_scene.find_child("animation_player", true, false)


func _find_node_named(node: Node, name: String, recursive: bool = true) -> Node3D:
	if not recursive:
		for child in node.get_children():
			if child.name.to_lower() == name and child is Node3D:
				return child
		return null
	for child in node.get_children():
		if child is Node3D and child.name.to_lower() == name:
			return child
		var found = _find_node_named(child, name, true)
		if found != null:
			return found
	return null


func _find_bone_in_skeleton(node: Node, bone_name: String) -> Node3D:
	var skeleton = node.find_child("Skeleton3D", true, false)
	if skeleton == null or skeleton.get_child_count() == 0:
		return null
	for child in skeleton.get_children():
		if child.name == bone_name and child is Node3D:
			return child
	return null


func _setup_hit_areas():
	_hit_areas = HitAreaController.new()
	add_child(_hit_areas)
	_hit_areas.setup(vrm_scene if vrm_scene != null else self, _head_bone, _hips_bone)
	_hit_areas.area_hit.connect(_on_hit_area)


func _on_hit_area(zone: String):
	play_animation("hitarea_" + zone + ".vrma")


func _setup_idle_behavior():
	_idle_timer = Timer.new()
	_idle_timer.one_shot = true
	_idle_timer.timeout.connect(_on_idle_timer)
	add_child(_idle_timer)
	_schedule_idle()


func _schedule_idle():
	if _tts_active or _current_emotion != "neutral":
		_idle_timer.start(randf_range(2.0, 5.0))
		return
	_idle_timer.start(randf_range(8.0, 15.0))


func _on_idle_timer():
	if _tts_active or _current_emotion != "neutral":
		_schedule_idle()
		return
	var anim = IDLE_MICRO_ANIMS[randi() % IDLE_MICRO_ANIMS.size()]
	play_animation(anim + ".vrma")
	_schedule_idle()


func _fit_camera():
	if _camera == null or vrm_scene == null:
		return
	var aabb = _get_vrm_aabb()
	if aabb.size.length() < 0.01:
		return
	var center = aabb.get_center()
	var size = aabb.size.length()
	var dist = max(size * 1.5, 2.5)
	_camera.global_position = Vector3(0, center.y * 0.8, dist)
	_camera.look_at(Vector3(center.x, center.y * 0.9, center.z))


func _get_vrm_aabb() -> AABB:
	var aabb = AABB()
	var first = true
	for mi in _mesh_instances:
		if mi.mesh == null: continue
		var global_aabb = mi.global_transform * mi.mesh.get_aabb()
		if first:
			aabb = global_aabb
			first = false
		else:
			aabb = aabb.merge(global_aabb)
	return aabb


func _load_idle_animation():
	if _animation_player == null:
		return
	var anim_lib = AnimationLibrary.new()
	var path = "/static/animations/idle_loop.vrma"
	var anim = await _load_vrma_http(path)
	if anim != null:
		anim_lib.add_animation("idle", anim)
		if _animation_player.has_animation_library(""):
			_animation_player.get_animation_library("").add_animation("idle", anim)
		else:
			_animation_player.add_animation_library("", anim_lib)
		_animation_player.play("idle")


func _load_vrma_http(url: String):
	var http = HTTPRequest.new()
	add_child(http)
	http.request(url)
	var response = await http.request_completed
	http.queue_free()
	if response[0] != HTTPRequest.RESULT_SUCCESS:
		return null
	var body = response[3] as PackedByteArray
	return _parse_vrma_animation(body)


func _parse_vrma_animation(data: PackedByteArray):
	var gltf = GLTFDocument.new()
	var state = GLTFState.new()
	var err = gltf.append_from_buffer(data, "", state)
	if err != OK:
		return null
	var anims = state.get_animations()
	if anims.is_empty():
		return null
	return anims[0]


func play_animation(name_or_path: String):
	if _animation_player == null:
		return
	if _animation_player.has_animation(name_or_path):
		_animation_player.play(name_or_path)
		await _animation_player.animation_finished
		if _animation_player.has_animation("idle"):
			_animation_player.play("idle")


func set_emotion(emotion: String):
	_current_emotion = emotion
	var expr = EMOTION_TO_EXPRESSION.get(emotion, null)
	for e in EXPRESSION_NAMES:
		_set_expression(e, 0.0)
	if expr != null:
		var value = 0.5 if emotion == "surprised" else 1.0
		_set_expression(expr, value)


func set_expression(name: String):
	for e in EXPRESSION_NAMES:
		_set_expression(e, 0.0)
	if EXPRESSION_NAMES.has(name):
		_set_expression(name, 1.0)


func _set_expression(name: String, value: float):
	_expression_targets[name] = value


func _set_blend_shape(name: String, value: float):
	var info = _blend_shape_map.get(name.to_lower())
	if info != null:
		info["mi"].set_blend_shape_value(info["idx"], clamp(value, 0.0, 1.0))


func start_lip_sync():
	_lip_scale = LIP_SYNC_SCALE_EMOTIVE if (_current_emotion != "neutral") else LIP_SYNC_SCALE_NEUTRAL
	_lip_sync_active = true


func stop_lip_sync():
	_lip_sync_active = false
	for e in ["aa", "ih", "ou", "ee", "oh"]:
		_set_blend_shape(e, 0.0)


func set_viseme(frame: Dictionary):
	var shape = frame.get("shape", {})
	var open = shape.get("open", 0.0) * _lip_scale
	var width = shape.get("width", 0.5) * _lip_scale
	var roundness = shape.get("round", 0.0) * _lip_scale

	_set_blend_shape("aa", open)
	_set_blend_shape("ih", (1.0 - width) * 0.5 * _lip_scale)
	_set_blend_shape("ou", roundness * _lip_scale)
	_set_blend_shape("ee", width * 0.5 * _lip_scale)
	_set_blend_shape("oh", (open * 0.5 + roundness * 0.5) * _lip_scale)


func set_mouth_open(value: float):
	_set_blend_shape("aa", clamp(value, 0.0, 1.0) * 0.5)
	for e in ["ih", "ou", "ee", "oh"]:
		_set_blend_shape(e, 0.0)


func set_tts_active(val: bool):
	_tts_active = val


func get_head_screen_position() -> Dictionary:
	if _head_bone == null or _camera == null:
		return {"x": 0.0, "y": 0.0, "visible": false}
	var world_pos = _head_bone.global_position + Vector3(0, 0.35, 0)
	var screen = _camera.unproject_position(world_pos)
	var viewport = get_viewport().get_visible_rect()
	var on_screen = screen.x >= 0 and screen.x <= viewport.size.x and screen.y >= 0 and screen.y <= viewport.size.y
	return {"x": screen.x, "y": screen.y, "visible": on_screen}


func _process(delta):
	if vrm_scene == null:
		return

	_update_blink(delta)
	_update_saccade(delta)
	_update_expressions(delta)
	_update_hit_areas()
	_update_head_position()

	for name in _expression_targets:
		var current = _get_blend_shape(name)
		var target = _expression_targets.get(name, 0.0)
		var blended = current + (target - current) * EXPRESSION_BLEND_RATE * delta
		_set_blend_shape(name, blended)


func _get_blend_shape(name: String) -> float:
	var info = _blend_shape_map.get(name.to_lower())
	if info != null:
		return info["mi"].get_blend_shape_value(info["idx"])
	return 0.0


func _update_blink(delta):
	if not _blink_enabled:
		return
	_blink_timer -= delta
	if _blink_timer <= 0 and _blink_value <= 0.01:
		_blink_value = 1.0
		_blink_timer = BLINK_CLOSE_MAX
	elif _blink_timer <= 0 and _blink_value > 0.01:
		_blink_value = 0.0
		_blink_timer = BLINK_OPEN_MAX
	_set_blend_shape("blink", _blink_value)


func _update_saccade(delta):
	_saccade_timer -= delta
	if _saccade_timer <= 0 and randf() < SACCADE_PROC:
		var yaw = (randf() - 0.5) * 2.0 * SACCADE_RADIUS
		var pitch = (randf() - 0.5) * 2.0 * SACCADE_RADIUS
		_saccade_target = Vector3(yaw, pitch, 0.0)
		_saccade_timer = SACCADE_MIN_INTERVAL

	var smooth = 1.0 - exp(-SACCADE_SMOOTH_FACTOR * delta)
	_saccade_current = _saccade_current.lerp(_saccade_target, smooth)

	if _head_bone != null:
		var rot = _head_bone.global_rotation
		rot.x += _saccade_current.y * 0.01
		rot.y += _saccade_current.x * 0.01
		_head_bone.global_rotation = rot


func _update_expressions(delta):
	pass


func _update_hit_areas():
	if _hit_areas != null and _hit_areas._enabled:
		_hit_areas.update_positions()


func _update_head_position():
	var pos = get_head_screen_position()
	if pos["x"] != _last_head_screen.x or pos["y"] != _last_head_screen.y:
		_last_head_screen = Vector2(pos["x"], pos["y"])
		head_position_changed.emit(pos["x"], pos["y"], pos["visible"])


func set_blink_enabled(val: bool):
	_blink_enabled = val
	if not val:
		_blink_value = 0.0
		_set_blend_shape("blink", 0.0)


func destroy():
	if _idle_timer:
		_idle_timer.queue_free()
	if _animation_player:
		_animation_player.stop()
	if _hit_areas:
		_hit_areas.destroy()
	if vrm_scene:
		vrm_scene.queue_free()
	queue_free()
