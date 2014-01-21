import subprocess
from Crypto.PublicKey import RSA


CREATE_GIT_REPO_SH = '''
git init {dir}
cd {dir}
git config user.email "author@example.com>"
git config user.name "A U Thore"
echo "echo Hello!" > ./kozmic.sh
git add ./kozmic.sh
git commit -m "Initial commit"
'''


COMMIT_TO_GIT_REPO_SH = '''
cd {dir}
touch ./content
echo "1" >> ./content
git add ./content
git commit -m "Commit"
'''


def create_git_repo(target_dir):
    """Creates git repository in :param:`target_dir`. Returns head SHA."""
    subprocess.call(
        CREATE_GIT_REPO_SH.format(dir=target_dir), shell=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return subprocess.check_output(
        'cd {} && git rev-parse HEAD'.format(target_dir),
        shell=True
    ).strip()


def add_commit_to_git_repo(target_dir):
    subprocess.call(
        COMMIT_TO_GIT_REPO_SH.format(dir=target_dir), shell=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return subprocess.check_output(
        'cd {}'.format(target_dir),
        shell=True
    ).strip()


def generate_private_key(passphrase):
    rsa_key = RSA.generate(1024)
    return rsa_key.exportKey(format='PEM', passphrase=passphrase)
