extends Node

class_name HitAreaController

signal area_hit(zone_name: String)

enum Zone { HEAD, CHEST, GROIN, LEG }

var avatar_node: Node3D = null
var head_bone: Node3D = null
var hips_bone: Node3D = null

var _areas: Dictionary = {}
var _enabled := false


func setup(avatar: Node3D, head: Node3D, hips: Node3D):
	avatar_node = avatar
	head_bone = head
	hips_bone = hips
	_create_zones()
	_enabled = true


func _create_zones():
	var zones = {
		Zone.HEAD: {"name": "head", "color": Color(1, 0, 0, 0.08)},
		Zone.CHEST: {"name": "chest", "color": Color(0, 1, 0, 0.08)},
		Zone.GROIN: {"name": "groin", "color": Color(0, 0, 1, 0.08)},
		Zone.LEG: {"name": "leg", "color": Color(1, 1, 0, 0.08)}
	}
	for zone in zones:
		var info = zones[zone]
		var area = Area3D.new()
		area.name = "HitArea_" + info["name"]
		area.input_event.connect(_on_area_input.bind(info["name"]))

		var col = CollisionShape3D.new()
		var shape = BoxShape3D.new()
		col.shape = shape
		area.add_child(col)
		_areas[zone] = {"node": area, "collision": col, "name": info["name"]}
		avatar_node.add_child(area)


func update_positions():
	if not _enabled or head_bone == null or hips_bone == null:
		return

	var head_pos = head_bone.global_position
	var hips_pos = hips_bone.global_position
	var head_above = (head_pos - hips_pos) * 0.2

	if _areas.has(Zone.HEAD):
		var a = _areas[Zone.HEAD]
		var half = head_above.length() * 0.6
		a["node"].global_position = head_pos + Vector3(0, half * 0.5, 0)
		var s = a["collision"].shape as BoxShape3D
		s.size = Vector3(0.4, half, 0.4)

	if _areas.has(Zone.CHEST):
		var a = _areas[Zone.CHEST]
		var center = Vector3(0, (head_pos.y - hips_pos.y) * 0.6 + hips_pos.y, 0)
		a["node"].global_position = center
		var s = a["collision"].shape as BoxShape3D
		s.size = Vector3(0.5, (head_pos.y - hips_pos.y) * 0.4, 0.4)

	if _areas.has(Zone.GROIN):
		var a = _areas[Zone.GROIN]
		var center = Vector3(0, hips_pos.y + (head_pos.y - hips_pos.y) * 0.15, 0)
		a["node"].global_position = center
		var s = a["collision"].shape as BoxShape3D
		s.size = Vector3(0.4, (head_pos.y - hips_pos.y) * 0.2, 0.3)

	if _areas.has(Zone.LEG):
		var a = _areas[Zone.LEG]
		var center = Vector3(0, (head_pos.y - hips_pos.y) * -0.1 + hips_pos.y, 0)
		a["node"].global_position = center
		var s = a["collision"].shape as BoxShape3D
		s.size = Vector3(0.4, (head_pos.y - hips_pos.y) * 0.3, 0.3)


func _on_area_input(_camera: Node, event: InputEvent, _event_pos: Vector3, _normal: Vector3, _shape_idx: int, zone_name: String):
	if event is InputEventMouseButton and event.button_index == MOUSE_BUTTON_LEFT and event.pressed:
		area_hit.emit(zone_name)


func set_enabled(val: bool):
	_enabled = val
	for zone in _areas:
		_areas[zone]["node"].visible = val


func destroy():
	_enabled = false
	for zone in _areas:
		if _areas[zone]["node"].get_parent():
			_areas[zone]["node"].queue_free()
	_areas.clear()
