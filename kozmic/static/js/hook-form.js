$(function () {
    $('textarea.editor').each(function() {
        var cm = CodeMirror.fromTextArea(this, {
            mode: 'shell',
            lineNumbers: true
        });
    });
});
