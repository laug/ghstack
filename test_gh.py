import textwrap
import doctest
import expecttest
import unittest
import subprocess
import warnings
import os
import shutil
import tempfile

import gh


def indent(text, prefix):
    return ''.join(prefix+line if line.strip() else line for line in text.splitlines(True))


def dump_github_state(github):
    r = github.graphql("""
      query {
        repository(name: "pytorch", owner: "pytorch") {
          pullRequests {
            nodes {
              number
              baseRefName
              headRefName
              title
              body
            }
          }
        }
      }
    """)
    prs = []
    for pr in r['data']['repository']['pullRequests']['nodes']:
        pr['body'] = indent(pr['body'], '    ')
        prs.append("#{number} {title} ({headRefName} -> {baseRefName})\n\n"
                   "{body}\n\n".format(**pr))
    return "".join(prs)


def create_pr(github):
    github.graphql("""
      mutation {
        createPullRequest(input: {
            baseRefName: "master",
            headRefName: "blah",
            title: "New PR",
            body: "What a nice PR this is",
            ownerId: 1000,
          }) {
          pullRequest {
            number
          }
        }
      }
    """)


class TestGh(expecttest.TestCase):
    # Starting up node takes 0.7s.  Don't do it every time.
    @classmethod
    def setUpClass(cls):
        port = 49152
        # Find an open port to run our tests on
        while True:
            cls.proc = subprocess.Popen(['node', 'github-fake/src/index.js', str(port)], stdout=subprocess.PIPE)
            r = cls.proc.stdout.readline()
            if not r.strip():
                cls.proc.terminate()
                cls.proc.wait()
                port +=1
                print("Retrying with port {}".format(port))
                continue
            break
        cls.github = gh.Endpoint("http://localhost:{}".format(port))

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait()

    def setUp(self):
        self.github.graphql("""
          mutation {
            resetGitHub(input: {}) {
              clientMutationId
            }
          }
        """)
        tmp_dir = tempfile.mkdtemp()

        # Set up a "parent" repository with an empty initial commit that we'll operate on
        upstream_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(upstream_dir))
        self.upstream_sh = gh.Shell(upstream_dir)
        self.upstream_sh.git("init", "--bare")
        tree = self.upstream_sh.git("write-tree")
        commit = self.upstream_sh.git("commit-tree", tree, input="Initial commit")
        self.upstream_sh.git("branch", "-f", "master", commit)

        local_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(local_dir))
        self.sh = gh.Shell(local_dir)
        self.sh.git("clone", upstream_dir, ".")

    # Just to make sure the GraphQL is working at all
    def test_smoketest(self):
        create_pr(self.github)
        self.assertExpected(dump_github_state(self.github), '''\
#500 New PR (blah -> master)

    What a nice PR this is

''')

    def test_simple(self):
        print("####################")
        print("### First commit")
        self.sh.git("commit", "--allow-empty", "-m", "Commit 1\n\nThis is my first commit")
        gh.main(github=self.github, sh=self.sh)
        print("####################")
        print("### Second commit")
        self.sh.git("commit", "--allow-empty", "-m", "Commit 2\n\nThis is my second commit")
        gh.main(github=self.github, sh=self.sh)
        self.assertExpected(dump_github_state(self.github), '''\
#500 Commit 1 (gh/ezyang/head/1 -> gh/ezyang/base/1)

    Commit 1

    This is my first commit

    Pull Request resolved: https://github.com/pytorch/pytorch/pull/500 (gh/ezyang/head/1)

#501 Commit 2 (gh/ezyang/head/2 -> gh/ezyang/base/2)

    This is my second commit

    Pull Request resolved: https://github.com/pytorch/pytorch/pull/501 (gh/ezyang/head/2)

''')



#   def load_tests(loader, tests, ignore):
#       tests.addTests(doctest.DocTestSuite(gh))
#       return tests


if __name__ == '__main__':
    unittest.main()