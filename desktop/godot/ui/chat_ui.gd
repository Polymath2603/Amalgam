extends Control

signal message_sent(text: String)

@onready var chat_log: RichTextLabel = $Panel/VBox/ChatLog
@onready var input_field: LineEdit = $Panel/VBox/Input/LineEdit
@onready var send_btn: Button = $Panel/VBox/Input/SendButton

var _messages: Array = []


func _ready():
	input_field.text_submitted.connect(_on_text_submitted)
	send_btn.pressed.connect(_on_send_pressed)


func _on_text_submitted(text: String):
	if text.strip_edges().is_empty():
		return
	_add_message("You", text)
	message_sent.emit(text)
	input_field.clear()


func _on_send_pressed():
	_on_text_submitted(input_field.text)


func add_assistant_message(text: String):
	_add_message("Assistant", text)


func add_thinking(text: String):
	_add_message("Thinking", "[i]" + text + "[/i]", Color.GRAY)


func add_error(text: String):
	_add_message("Error", text, Color.RED)


func _add_message(speaker: String, text: String, color: Color = Color.WHITE):
	var line = "[b]" + speaker + ":[/b] " + text
	_messages.append(line)
	if _messages.size() > 200:
		_messages.pop_front()
	chat_log.text = "\n".join(_messages)
	chat_log.scroll_to_line(chat_log.get_line_count() - 1)
