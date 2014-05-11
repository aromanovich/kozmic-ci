from sphinx.directives.code import CodeBlock


class CodeBlockWithVersionReplacement(CodeBlock):
    def run(self):
        env = self.state.document.settings.env
        version = str(env.config['version'])
        self.content = [line.replace('|version|', version) for line in self.content]
        return CodeBlock.run(self)


def setup(app):
    app.add_crossref_type(
        directivename='setting',
        rolename='setting',
        indextemplate='pair: %s; setting',
    )
    app.add_directive('code-block-w-version-replacement', CodeBlockWithVersionReplacement)
