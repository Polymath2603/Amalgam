extends Node

const DEFAULT_CHARACTER := "res://assets/characters/default/model.vrm"

@onready var avatar: AvatarController = $Avatar
@onready var camera: Camera3D = $Camera3D

func _ready():
	_load_default_character()

func _load_default_character():
	if not ResourceLoader.exists(DEFAULT_CHARACTER):
		push_warning("VRM not found at: ", DEFAULT_CHARACTER)
		return
	var scene = load(DEFAULT_CHARACTER)
	if scene == null or not scene is PackedScene:
		push_error("Failed to load VRM scene")
		return
	avatar.load_vrm(DEFAULT_CHARACTER)
