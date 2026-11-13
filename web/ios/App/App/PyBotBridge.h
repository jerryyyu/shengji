#ifndef PyBotBridge_h
#define PyBotBridge_h

/// Starts the embedded interpreter with PYTHONHOME = <resources>/python and
/// imports offline_bot.  Returns NULL on success, else a malloc'd error.
char *pybot_start(const char *resource_path);

/// offline_bot.call(name, args_json): a malloc'd UTF-8 result; an exception
/// comes back as "ERROR: <traceback>".  Any thread; takes the GIL.
char *pybot_call(const char *name, const char *args_json);

#endif
