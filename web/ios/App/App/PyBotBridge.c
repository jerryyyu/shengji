#include "PyBotBridge.h"
#include <Python/Python.h>
#include <stdlib.h>
#include <string.h>

static PyObject *pybot_module = NULL;

static char *dup_or_null(const char *s) { return s ? strdup(s) : NULL; }

static char *format_error(void) {
    PyObject *exc = PyErr_GetRaisedException();
    char *out = NULL;
    PyObject *tb = PyImport_ImportModule("traceback");
    if (tb && exc) {
        PyObject *lines = PyObject_CallMethod(tb, "format_exception", "O", exc);
        PyObject *empty = PyUnicode_FromString("");
        PyObject *joined = (lines && empty) ? PyUnicode_Join(empty, lines) : NULL;
        if (joined) {
            const char *u = PyUnicode_AsUTF8(joined);
            size_t n = strlen(u) + 8;
            out = malloc(n);
            snprintf(out, n, "ERROR: %s", u);
        }
        Py_XDECREF(joined); Py_XDECREF(empty); Py_XDECREF(lines);
    }
    Py_XDECREF(tb); Py_XDECREF(exc);
    PyErr_Clear();
    return out ? out : strdup("ERROR: (unformattable exception)");
}

static int append_path(PyConfig *config, const char *path) {
    wchar_t *w = Py_DecodeLocale(path, NULL);
    PyStatus st = PyWideStringList_Append(&config->module_search_paths, w);
    PyMem_RawFree(w);
    return PyStatus_Exception(st) ? -1 : 0;
}

char *pybot_start(const char *resource_path) {
    if (pybot_module) return NULL;
    char buf[4096];
    PyPreConfig pre;
    PyConfig config;
    PyPreConfig_InitIsolatedConfig(&pre);
    pre.utf8_mode = 1;
    PyStatus st = Py_PreInitialize(&pre);
    if (PyStatus_Exception(st)) return dup_or_null(st.err_msg ? st.err_msg : "preinit failed");

    PyConfig_InitIsolatedConfig(&config);
    config.use_system_logger = 1;
    config.buffered_stdio = 0;
    config.write_bytecode = 0;
    config.install_signal_handlers = 0;
    config.site_import = 0;
    snprintf(buf, sizeof buf, "%s/python", resource_path);
    st = PyConfig_SetBytesString(&config, &config.home, buf);
    if (PyStatus_Exception(st)) { PyConfig_Clear(&config); return strdup("cannot set home"); }
    config.module_search_paths_set = 1;
    const char *subdirs[] = {"python/lib/python3.14", "python/lib/python3.14/lib-dynload",
                             "python/app", "python/app_packages"};
    for (int i = 0; i < 4; i++) {
        snprintf(buf, sizeof buf, "%s/%s", resource_path, subdirs[i]);
        if (append_path(&config, buf)) { PyConfig_Clear(&config); return strdup("cannot set path"); }
    }
    st = Py_InitializeFromConfig(&config);
    PyConfig_Clear(&config);
    if (PyStatus_Exception(st)) return dup_or_null(st.err_msg ? st.err_msg : "init failed");

    pybot_module = PyImport_ImportModule("offline_bot");
    char *err = pybot_module ? NULL : format_error();
    // Release the GIL; every later call takes it with PyGILState_Ensure.
    PyEval_SaveThread();
    return err;
}

char *pybot_call(const char *name, const char *args_json) {
    if (!pybot_module) return strdup("ERROR: interpreter not started");
    PyGILState_STATE g = PyGILState_Ensure();
    char *out = NULL;
    PyObject *r = PyObject_CallMethod(pybot_module, "call", "ss", name, args_json);
    if (r && PyUnicode_Check(r)) {
        out = strdup(PyUnicode_AsUTF8(r));
    } else if (r) {
        out = strdup("ERROR: call returned a non-string");
    } else {
        out = format_error();
    }
    Py_XDECREF(r);
    PyGILState_Release(g);
    return out;
}
