extends Node

signal connected()
signal disconnected()
signal message_received(msg: Dictionary)
signal tts_audio(audio_data: PackedByteArray, sample_rate: int)
signal thinking(text: String)
signal error(msg: String)

var _ws: WebSocketPeer = null
var _url: String = "ws://localhost:8000/ws/chat"
var _connected := false
var _reconnect_timer: float = 0.0
var _reconnect_delay: float = 5.0
var _should_reconnect := true


func connect_to(url: String = ""):
	if url != "":
		_url = url
	_ws = WebSocketPeer.new()
	var err = _ws.connect_to_url(_url)
	if err != OK:
		push_error("WebSocket connect failed: ", err)
		_ws = null


func close_ws():
	_should_reconnect = false
	if _ws != null:
		_ws.close()
		_ws = null
	_connected = false


func send_message(text: String):
	if _ws == null or not _connected:
		push_warning("Cannot send message: not connected")
		return
	var data = JSON.stringify({"text": text, "type": "message"})
	_ws.send_text(data)


func send_tts(text: String, voice: String = ""):
	if _ws == null or not _connected:
		return
	var data = JSON.stringify({"text": text, "type": "tts", "voice": voice})
	_ws.send_text(data)


func _process(delta):
	if _ws == null:
		if _should_reconnect:
			_reconnect_timer -= delta
			if _reconnect_timer <= 0:
				_reconnect_timer = _reconnect_delay
				connect_to()
		return

	_ws.poll()
	var state = _ws.get_ready_state()

	match state:
		WebSocketPeer.STATE_OPEN:
			if not _connected:
				_connected = true
				emit_signal("connected")
			while _ws.get_available_packet_count() > 0:
				var packet = _ws.get_packet()
				if packet is PackedByteArray:
					_handle_packet(packet)

		WebSocketPeer.STATE_CLOSED:
			if _connected:
				_connected = false
				emit_signal("disconnected")
			_ws = null
			if _should_reconnect:
				_reconnect_timer = _reconnect_delay


func _handle_packet(packet: PackedByteArray):
	var text = packet.get_string_from_utf8()
	var json = JSON.new()
	var err = json.parse(text)
	if err != OK:
		push_warning("Failed to parse message: ", err)
		return
	var msg = json.data as Dictionary
	var msg_type = msg.get("type", "")

	match msg_type:
		"thinking":
			emit_signal("thinking", msg.get("text", ""))
		"content":
			emit_signal("message_received", msg)
		"audio":
			var audio_raw = msg.get("audio", "")
			var rate = msg.get("sample_rate", 24000)
			var bytes = Marshalls.base64_to_raw(audio_raw)
			emit_signal("tts_audio", bytes, rate)
		"error":
			emit_signal("error", msg.get("text", ""))
		_:
			emit_signal("message_received", msg)
