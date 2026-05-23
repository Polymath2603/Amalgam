




"""Generated protocol buffer code."""
from google .protobuf import descriptor as _descriptor 
from google .protobuf import descriptor_pool as _descriptor_pool 
from google .protobuf import runtime_version as _runtime_version 
from google .protobuf import symbol_database as _symbol_database 
from google .protobuf .internal import builder as _builder 
_runtime_version .ValidateProtobufRuntimeVersion (
_runtime_version .Domain .PUBLIC ,
6 ,
31 ,
1 ,
'',
'agent.proto'
)


_sym_db =_symbol_database .Default ()




DESCRIPTOR =_descriptor_pool .Default ().AddSerializedFile (b'\n\x0b\x61gent.proto\"X\n\x0b\x43hatRequest\x12\x0e\n\x04text\x18\x01 \x01(\tH\x00\x12.\n\x11permission_action\x18\x02 \x01(\x0b\x32\x11.PermissionActionH\x00\x42\t\n\x07payload\"/\n\x10PermissionAction\x12\x0e\n\x06\x61\x63tion\x18\x01 \x01(\t\x12\x0b\n\x03\x63md\x18\x02 \x01(\t\"\xcc\x01\n\x0c\x43hatResponse\x12\x14\n\ntext_chunk\x18\x01 \x01(\tH\x00\x12\x1e\n\ttool_call\x18\x02 \x01(\x0b\x32\t.ToolCallH\x00\x12\x30\n\x12permission_request\x18\x03 \x01(\x0b\x32\x12.PermissionRequestH\x00\x12\x0f\n\x05\x65rror\x18\x04 \x01(\tH\x00\x12\x0e\n\x04\x64one\x18\x05 \x01(\x08H\x00\x12\x14\n\nsession_id\x18\x06 \x01(\tH\x00\x12\x12\n\x08thinking\x18\x07 \x01(\tH\x00\x42\t\n\x07payload\"+\n\x08ToolCall\x12\x0c\n\x04name\x18\x01 \x01(\t\x12\x11\n\targs_json\x18\x02 \x01(\t\"1\n\x11PermissionRequest\x12\x0b\n\x03\x63md\x18\x01 \x01(\t\x12\x0f\n\x07options\x18\x02 \x03(\t27\n\x0c\x41gentService\x12\'\n\x04\x43hat\x12\x0c.ChatRequest\x1a\r.ChatResponse(\x01\x30\x01\x62\x06proto3')

_globals =globals ()
_builder .BuildMessageAndEnumDescriptors (DESCRIPTOR ,_globals )
_builder .BuildTopDescriptorsAndMessages (DESCRIPTOR ,'agent_pb2',_globals )
if not _descriptor ._USE_C_DESCRIPTORS :
  DESCRIPTOR ._loaded_options =None 
  _globals ['_CHATREQUEST']._serialized_start =15 
  _globals ['_CHATREQUEST']._serialized_end =103 
  _globals ['_PERMISSIONACTION']._serialized_start =105 
  _globals ['_PERMISSIONACTION']._serialized_end =152 
  _globals ['_CHATRESPONSE']._serialized_start =155 
  _globals ['_CHATRESPONSE']._serialized_end =359 
  _globals ['_TOOLCALL']._serialized_start =361 
  _globals ['_TOOLCALL']._serialized_end =404 
  _globals ['_PERMISSIONREQUEST']._serialized_start =406 
  _globals ['_PERMISSIONREQUEST']._serialized_end =455 
  _globals ['_AGENTSERVICE']._serialized_start =457 
  _globals ['_AGENTSERVICE']._serialized_end =512 

