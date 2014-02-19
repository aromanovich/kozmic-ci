$(function () {
    $('textarea.editor').each(function() {
        var cm = CodeMirror.fromTextArea(this, {
            mode: 'shell',
            lineNumbers: true
        });
        cm.setSize(null, 200);
    });
});
