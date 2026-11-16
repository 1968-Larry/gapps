// Compatibility for TinyMCE 7/8 with plugins written for TinyMCE 4-6
// (tinymce-variable): editor.getParam(), editor.fire() and tinymce.walk() were
// removed.
// Load after tinymce.min.js and before those plugins.
(function () {
  if (typeof tinymce === "undefined") return;

  if (typeof tinymce.walk !== "function") {
    // Same as the old tinymce.util.Tools.walk: calls f for every node below o,
    // following the property n (for example "childNodes")
    tinymce.walk = function walk(o, f, n, s) {
      if (!o) return;
      var items = n ? o[n] : o;
      if (!items) return;
      for (var i = 0; i < items.length; i++) {
        if (f.call(s, items[i], i, n) === false) return false;
        if (walk(items[i], f, n, s) === false) return false;
      }
    };
  }
  tinymce.on("AddEditor", function (e) {
    var editor = e.editor;
    if (typeof editor.fire !== "function" && typeof editor.dispatch === "function") {
      editor.fire = function () {
        return editor.dispatch.apply(editor, arguments);
      };
    }
    if (typeof editor.getParam !== "function" && editor.options) {
      // Old plugins read their own settings without registering them; register
      // on first use (raw value), the initial value from tinymce.init() is kept.
      editor.getParam = function (name, defaultValue) {
        if (!editor.options.isRegistered(name)) {
          editor.options.register(name, {
            processor: function (value) {
              return { valid: true, value: value };
            },
            default: defaultValue,
          });
        }
        var value = editor.options.get(name);
        return value === undefined ? defaultValue : value;
      };
    }
  });
})();
