from pathlib import Path
import subprocess

import pytest

LIB = Path(__file__).resolve().parents[1] / 'lib.sh'


def git(path, *args):
  return subprocess.run(['git', '-C', str(path), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def checkout(tmp_path):
  source = tmp_path / 'source.git'
  source.mkdir()
  git(source, 'init', '-q', '-b', 'sp-ody-dev')
  git(source, '-c', 'user.name=Test', '-c', 'user.email=test@example.com', 'commit', '-q', '--allow-empty', '-m', 'init')
  dest = tmp_path / 'checkout'
  subprocess.run(['git', 'clone', '-q', str(source), str(dest)], check=True)
  return source, dest


def update(source, dest):
  return subprocess.run(['bash', '-euc', 'source "$1"; ody_checkout "$2" sp-ody-dev "$3"',
                         '_', str(LIB), str(source), str(dest)], capture_output=True, text=True)


def test_clean_checkout_fast_forwards(checkout):
  source, dest = checkout
  git(source, '-c', 'user.name=Test', '-c', 'user.email=test@example.com', 'commit', '-q', '--allow-empty', '-m', 'next')
  result = update(source, dest)
  assert result.returncode == 0, result.stderr
  assert git(dest, 'rev-parse', 'HEAD') == git(source, 'rev-parse', 'HEAD')


@pytest.mark.parametrize('problem', ['dirty', 'wrong_origin', 'diverged'])
def test_refuses_to_discard_local_work(checkout, problem):
  source, dest = checkout
  if problem == 'dirty':
    (dest / 'keep.txt').write_text('local work')
  elif problem == 'wrong_origin':
    git(dest, 'remote', 'set-url', 'origin', 'https://example.com/other.git')
  else:
    for repo, message in ((source, 'remote'), (dest, 'local')):
      git(repo, '-c', 'user.name=Test', '-c', 'user.email=test@example.com', 'commit', '-q', '--allow-empty', '-m', message)
  head = git(dest, 'rev-parse', 'HEAD')
  result = update(source, dest)
  assert result.returncode != 0
  assert git(dest, 'rev-parse', 'HEAD') == head
  if problem == 'dirty':
    assert (dest / 'keep.txt').read_text() == 'local work'
