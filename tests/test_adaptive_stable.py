import unittest
import os
import sys
# Ensure ok-script library in the current dev directory is imported first
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import time
import numpy as np
import cv2
from ok.task.task import ExecutorOperation
from ok.feature.Box import Box


class MockExecutor:
    def __init__(self):
        self.scene = "MockScene"
        self.exit_event = MockEvent()
        self.method = MockMethod()
        self.debug = True
        self._frame = None

    @property
    def frame(self):
        return self._frame

    def sleep(self, timeout):
        time.sleep(timeout)


class MockEvent:
    def is_set(self):
        return False


class MockMethod:
    def __init__(self):
        self.width = 1920
        self.height = 1080


class MockApp:
    pass


class TestAdaptiveStable(unittest.TestCase):

    def setUp(self):
        # Create a test instance of ExecutorOperation
        self.executor = MockExecutor()
        self.app = MockApp()
        self.op = ExecutorOperation(self.executor, self.app)

        # Create test frames (1920x1080 RGB)
        self.frame_black = np.zeros((1080, 1920, 3), dtype=np.uint8)
        self.frame_white = np.ones((1080, 1920, 3), dtype=np.uint8) * 255

        # Create a frame with local changes
        self.frame_partial = np.zeros((1080, 1920, 3), dtype=np.uint8)
        # Paint a 400x400 white region in the center
        self.frame_partial[340:740, 760:1160] = 255

    def test_calculate_frame_diff_basic(self):
        # 1. Identical frames comparison, difference should be 0.0
        diff = self.op.calculate_frame_diff(self.frame_black, self.frame_black)
        self.assertEqual(diff, 0.0)

        # 2. Black vs White frames comparison, difference should be extremely large (~255.0)
        diff = self.op.calculate_frame_diff(self.frame_black, self.frame_white)
        self.assertAlmostEqual(diff, 255.0, places=1)

        # 3. Local variance comparison, difference should be proportional
        diff = self.op.calculate_frame_diff(self.frame_black, self.frame_partial)
        # Area ratio 400x400 / 1920x1080 ~= 7.7%
        # Mean difference should be around 255 * 7.7% ~= 19.6
        self.assertTrue(15.0 < diff < 25.0, f"Expected diff around 19.6, got {diff}")

    def test_calculate_frame_diff_roi(self):
        # Test ROI local detection
        # Variance region in the center
        roi_match = Box(760, 340, 400, 400)
        # No variance region in the top-right
        roi_empty = Box(1500, 100, 200, 200)

        # Within the variance region, difference should be 255.0
        diff_match = self.op.calculate_frame_diff(self.frame_black, self.frame_partial, roi=roi_match)
        self.assertAlmostEqual(diff_match, 255.0, places=1)

        # Within the no variance region, difference should be 0.0
        diff_empty = self.op.calculate_frame_diff(self.frame_black, self.frame_partial, roi=roi_empty)
        self.assertEqual(diff_empty, 0.0)

    def test_calculate_frame_diff_preprocessed_2d(self):
        # Test directly passing preprocessed 2D arrays to calculate_frame_diff
        p_black = self.op._preprocess_frame(self.frame_black)
        p_partial = self.op._preprocess_frame(self.frame_partial)

        # Verify shape is 2D
        self.assertEqual(len(p_black.shape), 2)
        self.assertEqual(len(p_partial.shape), 2)

        # Test comparison without exception
        diff = self.op.calculate_frame_diff(p_black, p_partial)
        self.assertTrue(15.0 < diff < 25.0, f"Expected preprocessed diff around 19.6, got {diff}")

    def test_performance_benchmark(self):
        # Performance benchmark: verify downsampled comparison is extremely fast (within 0.5 ms)
        runs = 100
        start = time.time()
        for _ in range(runs):
            self.op.calculate_frame_diff(self.frame_black, self.frame_partial)
        duration = time.time() - start
        avg_time_ms = (duration / runs) * 1000

        print(f"\n[Performance Benchmark] Avg calculate_frame_diff time: {avg_time_ms:.3f} ms")
        # Typically < 0.3 ms on modern CPUs, set a relaxed safety margin of 5.0 ms for testing
        self.assertTrue(avg_time_ms < 5.0, f"Performance too slow: {avg_time_ms} ms")

    def test_wait_page_stable_large_motion(self):
        # Simulate a major page transition (e.g. large page opening then stabilizing)
        # Diff sequence: 0.0 -> transition start (18.0) -> animation ending (8.0 -> 3.0 -> 0.5 -> 0.1 -> 0.1 -> 0.1)
        frames_sequence = [
            self.frame_black,  # init
            self.frame_partial,  # 18.0 diff
            self.create_gray_frame(120),  # 8.0 diff
            self.create_gray_frame(45),  # 3.0 diff
            self.create_gray_frame(8),  # 0.5 diff
            self.create_gray_frame(1.5),  # 0.1 diff
            self.create_gray_frame(1.5),  # 0.1 diff
            self.create_gray_frame(1.5),  # 0.1 diff
            self.create_gray_frame(1.5),
        ]

        self.setup_mock_frames(frames_sequence)

        # Large motion detected (max_drift >= 1.0).
        # Verify that wait_page_stable detects convergence (Sm < 0.08) and exits early.
        success = self.op.wait_page_stable(timeout=2.0, check_interval=0.001, stable_frames=3)
        self.assertTrue(success)
        # Ensure successful exit before depleting all mock frames
        self.assertTrue(self.frame_index < len(frames_sequence))

    def test_wait_page_stable_small_motion(self):
        # Simulate a minor dialog transition (small variance, low peak)
        # Diff sequence: 0.0 -> transition start (1.8) -> stable (0.4 -> 0.1 -> 0.1 -> 0.1)
        frames_sequence = [
            self.frame_black,  # init
            self.create_gray_frame(25),  # 1.8 diff
            self.create_gray_frame(6),  # 0.4 diff
            self.create_gray_frame(1.5),  # 0.1 diff
            self.create_gray_frame(1.5),  # 0.1 diff
            self.create_gray_frame(1.5),  # 0.1 diff
            self.create_gray_frame(1.5),
        ]

        self.setup_mock_frames(frames_sequence)

        # Peak max_drift is around 1.8 (exceeds 1.0).
        # Verify that wait_page_stable detects Sm convergence and exits early.
        success = self.op.wait_page_stable(timeout=2.0, check_interval=0.001, stable_frames=3)
        self.assertTrue(success)
        self.assertTrue(self.frame_index < len(frames_sequence))

    def test_wait_page_stable_no_motion(self):
        # Simulate a click with no page change (e.g., clicking blank area or inactive button)
        # Diff sequence: 0.0 -> 0.05 -> 0.05 -> 0.05 (consistently below min_diff trigger threshold)
        frames_sequence = [
            self.frame_black,
            self.create_gray_frame(0.7),
            self.create_gray_frame(0.7),
            self.create_gray_frame(0.7),
            self.create_gray_frame(0.7),
            self.create_gray_frame(0.7),
            self.create_gray_frame(0.7),
            self.create_gray_frame(0.7),
            self.create_gray_frame(0.7),
        ]

        self.setup_mock_frames(frames_sequence)

        # Since peak drift is extremely small (max_drift < 1.0), it falls into the loading/network defense block.
        # Verify that it exits early after meeting the defense shield frame count (N_shield).
        success = self.op.wait_page_stable(timeout=2.0, check_interval=0.001, stable_frames=2)
        # No significant variance, should exit immediately and not consume all mock frames
        self.assertTrue(success)
        self.assertTrue(self.frame_index < len(frames_sequence))

    def test_wait_page_stable_interaction_awareness(self):
        # Test defense shield window lengths based on interaction state
        # Create a sufficiently long frames sequence to avoid frame exhaustion.
        frames_sequence = [self.frame_black] + [self.create_gray_frame(0.7)] * 20

        # Scenario 1: With prior interaction -> should use full safety defense shield.
        # timeout=1.0, check_interval=0.05. T_shield = min(3.0, 0.8) = 0.8s -> N_shield = 16.
        # It requires frame_count > 16 (i.e. 17) to early exit. Thus, it exits at frame_index = 18.
        self.setup_mock_frames(frames_sequence)
        self.op._has_interaction_since_last_stable = True
        success = self.op.wait_page_stable(timeout=1.0, check_interval=0.05, stable_frames=3)
        self.assertTrue(success)
        self.assertEqual(self.frame_index, 17)  # Waited the full long safety window

        # Scenario 2: Without prior interaction -> should use dynamic short confirmation window (N_shield=2) and exit fast (return True).
        # timeout=1.0, check_interval=0.05. N_shield = 2.
        # It will early exit when frame_count > 2 (i.e. frame_count=4, since history_limit=4) in ~0.2s.
        self.setup_mock_frames(frames_sequence)
        self.op._has_interaction_since_last_stable = False
        success = self.op.wait_page_stable(timeout=1.0, check_interval=0.05, stable_frames=3)
        self.assertTrue(success)
        self.assertEqual(self.frame_index, 4)  # Exited early exactly after 4 frames

    # --- Helper Methods ---
    def create_gray_frame(self, gray_value):
        # Create a 1920x1080 frame with a uniform gray value
        return np.ones((1080, 1920, 3), dtype=np.uint8) * int(gray_value)

    def setup_mock_frames(self, frames_list):
        self.mock_frames = frames_list
        self.frame_index = 0

        # Mock self.frame and self.next_frame() properties/methods
        # In ExecutorOperation, self.frame property dynamically calls self.executor.frame
        self.op.executor._frame = self.mock_frames[0]

        def mock_next_frame():
            self.frame_index += 1
            if self.frame_index < len(self.mock_frames):
                frame = self.mock_frames[self.frame_index]
            else:
                frame = self.mock_frames[-1]
            self.op.executor._frame = frame
            return frame

        self.op.next_frame = mock_next_frame


if __name__ == '__main__':
    unittest.main()
