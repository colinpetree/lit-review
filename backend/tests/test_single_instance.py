"""The one-copy-at-a-time lock."""

import gc
import subprocess
import sys
import time

import pytest

import single_instance
from procutil import kill_tree

HOLDER = """
import sys, time
import single_instance
lock = single_instance.acquire(sys.argv[1])
print("HOLDING", flush=True)
time.sleep(120)
"""


@pytest.fixture
def lock_path(tmp_path):
    return tmp_path / "state" / "instance.lock"


@pytest.fixture
def start_holder(lock_path):
    """A separate process that takes the lock and keeps it until it is killed."""
    procs = []

    def start():
        proc = subprocess.Popen(
            [sys.executable, "-c", HOLDER, str(lock_path)],
            stdout=subprocess.PIPE,
            text=True,
            cwd=str(__import__("procutil").BACKEND_DIR),
        )
        procs.append(proc)
        assert proc.stdout.readline().strip() == "HOLDING"
        return proc

    yield start
    for proc in procs:
        kill_tree(proc)


class TestAcquire:
    def test_the_first_taker_gets_it_and_the_second_is_refused(self, lock_path):
        first = single_instance.acquire(lock_path)
        try:
            with pytest.raises(single_instance.AlreadyRunning):
                single_instance.acquire(lock_path)
        finally:
            first.release()

    def test_it_can_be_taken_again_once_released(self, lock_path):
        single_instance.acquire(lock_path).release()
        again = single_instance.acquire(lock_path)
        again.release()

    def test_a_refused_attempt_does_not_disturb_the_holder(self, lock_path):
        first = single_instance.acquire(lock_path)
        try:
            for _ in range(3):
                with pytest.raises(single_instance.AlreadyRunning):
                    single_instance.acquire(lock_path)
            assert first.is_locked
        finally:
            first.release()

    def test_missing_folders_are_created(self, tmp_path):
        deep = tmp_path / "a" / "b" / "c" / "instance.lock"
        lock = single_instance.acquire(deep)
        try:
            assert deep.parent.is_dir()
        finally:
            lock.release()

    def test_a_string_path_works_too(self, lock_path):
        lock = single_instance.acquire(str(lock_path))
        lock.release()

    def test_different_files_do_not_conflict(self, tmp_path):
        a = single_instance.acquire(tmp_path / "one.lock")
        b = single_instance.acquire(tmp_path / "two.lock")
        a.release()
        b.release()

    def test_a_lock_that_is_dropped_is_released(self, lock_path):
        lock = single_instance.acquire(lock_path)
        del lock
        gc.collect()
        single_instance.acquire(lock_path).release()

    def test_the_refusal_names_the_file(self, lock_path):
        lock = single_instance.acquire(lock_path)
        try:
            with pytest.raises(single_instance.AlreadyRunning, match="instance.lock"):
                single_instance.acquire(lock_path)
        finally:
            lock.release()


class TestAcrossProcesses:
    def test_a_lock_held_by_another_process_refuses_us(self, lock_path, start_holder):
        start_holder()
        with pytest.raises(single_instance.AlreadyRunning):
            single_instance.acquire(lock_path)

    def test_a_killed_holder_leaves_no_stale_lock(self, lock_path, start_holder):
        holder = start_holder()
        with pytest.raises(single_instance.AlreadyRunning):
            single_instance.acquire(lock_path)

        kill_tree(holder)  # a hard kill: no chance to clean up after itself

        deadline = time.monotonic() + 5
        while True:
            try:
                single_instance.acquire(lock_path).release()
                break
            except single_instance.AlreadyRunning:
                assert time.monotonic() < deadline, "the lock was still held after its process was killed"
                time.sleep(0.1)

    def test_a_leftover_lock_file_does_not_block_anyone(self, lock_path):
        # What a crashed copy can leave behind (filelock removes the file on a
        # clean release on Windows, but not everywhere): the file means nothing,
        # only a lock actually held on it does.
        lock_path.parent.mkdir(parents=True)
        lock_path.write_text("left over from a copy that crashed")
        single_instance.acquire(lock_path).release()
        single_instance.acquire(lock_path).release()
