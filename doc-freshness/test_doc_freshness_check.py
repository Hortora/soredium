import json
import os
import tempfile
import unittest

from doc_freshness_check import parse_anchors, AnchoredDoc, find_anchored_docs, detect_stale, StaleCandidate


class TestParseAnchors(unittest.TestCase):

    def test_parses_full_anchor_frontmatter(self):
        content = """---
capability: notifications
audience: consumer
repo: casehub-platform
anchors:
  classes:
    - io.casehub.platform.notification.NotificationBridge
    - io.casehub.platform.notification.SubscriptionEngine
  spis:
    - io.casehub.platform.notification.spi.DeliveryChannel
  config-keys:
    - casehub.notification.digest.interval
  protocols:
    - notification-delivery-contract
---

# Notifications

Send notifications to users via multiple channels.
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write(content)
            path = f.name
        try:
            result = parse_anchors(path)
            self.assertEqual(result['capability'], 'notifications')
            self.assertEqual(result['audience'], 'consumer')
            self.assertEqual(result['repo'], 'casehub-platform')
            self.assertIn('io.casehub.platform.notification.NotificationBridge',
                          result['anchors']['classes'])
            self.assertIn('io.casehub.platform.notification.spi.DeliveryChannel',
                          result['anchors']['spis'])
            self.assertIn('casehub.notification.digest.interval',
                          result['anchors']['config-keys'])
            self.assertIn('notification-delivery-contract',
                          result['anchors']['protocols'])
        finally:
            os.unlink(path)

    def test_no_frontmatter_returns_none(self):
        content = "# Just a heading\n\nNo frontmatter here.\n"
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write(content)
            path = f.name
        try:
            result = parse_anchors(path)
            self.assertIsNone(result)
        finally:
            os.unlink(path)

    def test_frontmatter_without_anchors_returns_metadata_only(self):
        content = """---
capability: notifications
audience: consumer
repo: casehub-platform
---

# Notifications
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write(content)
            path = f.name
        try:
            result = parse_anchors(path)
            self.assertEqual(result['capability'], 'notifications')
            self.assertEqual(result['anchors'], {})
        finally:
            os.unlink(path)

    def test_verified_current_annotation_parsed(self):
        content = """---
capability: notifications
audience: consumer
repo: casehub-platform
verified-current: "2026-08-31 | commit:abc123"
anchors:
  classes:
    - io.casehub.platform.notification.NotificationBridge
---

# Notifications
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write(content)
            path = f.name
        try:
            result = parse_anchors(path)
            self.assertIn('2026-08-31', result['verified-current'])
        finally:
            os.unlink(path)


class TestDetectStale(unittest.TestCase):

    def _make_doc(self, path='notifications.md', classes=None, spis=None,
                  config_keys=None, protocols=None, verified=None):
        return AnchoredDoc(
            path=path, capability='notifications', audience='consumer',
            repo='casehub-platform',
            anchors={
                k: v for k, v in [
                    ('classes', classes or []),
                    ('spis', spis or []),
                    ('config-keys', config_keys or []),
                    ('protocols', protocols or []),
                ] if v
            },
            verified_current=verified,
        )

    def test_class_change_flags_section(self):
        doc = self._make_doc(classes=[
            'io.casehub.platform.notification.NotificationBridge'
        ])
        diff = ['platform/src/main/java/io/casehub/platform/notification/NotificationBridge.java']
        result = detect_stale(diff, [doc])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].anchor_type, 'classes')

    def test_unrelated_change_no_flag(self):
        doc = self._make_doc(classes=[
            'io.casehub.platform.notification.NotificationBridge'
        ])
        diff = ['engine/src/main/java/io/casehub/engine/CaseEngine.java']
        result = detect_stale(diff, [doc])
        self.assertEqual(len(result), 0)

    def test_verified_current_suppresses_flag(self):
        doc = self._make_doc(
            classes=['io.casehub.platform.notification.NotificationBridge'],
            verified='2026-08-31 | commit:abc123'
        )
        diff = ['platform/src/main/java/io/casehub/platform/notification/NotificationBridge.java']
        result = detect_stale(diff, [doc])
        self.assertEqual(len(result), 0)

    def test_spi_change_flags_section(self):
        doc = self._make_doc(spis=[
            'io.casehub.platform.notification.spi.DeliveryChannel'
        ])
        diff = ['platform-api/src/main/java/io/casehub/platform/notification/spi/DeliveryChannel.java']
        result = detect_stale(diff, [doc])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].anchor_type, 'spis')

    def test_config_key_change_flags_section(self):
        doc = self._make_doc(config_keys=['casehub.notification.digest.interval'])
        diff = ['src/main/resources/application.properties']
        result = detect_stale(diff, [doc])
        self.assertEqual(len(result), 1)

    def test_deduplicates_multiple_file_matches(self):
        doc = self._make_doc(classes=[
            'io.casehub.platform.notification.NotificationBridge'
        ])
        diff = [
            'platform/src/main/java/io/casehub/platform/notification/NotificationBridge.java',
            'platform/src/test/java/io/casehub/platform/notification/NotificationBridgeTest.java',
        ]
        result = detect_stale(diff, [doc])
        self.assertEqual(len(result), 1)


class TestAnchorIntegrity(unittest.TestCase):

    def test_find_anchored_docs_in_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cap_dir = os.path.join(tmpdir, 'capabilities')
            os.makedirs(cap_dir)
            with open(os.path.join(cap_dir, 'notifications.md'), 'w') as f:
                f.write("""---
capability: notifications
audience: consumer
repo: casehub-platform
anchors:
  classes:
    - io.casehub.platform.notification.NotificationBridge
---

# Notifications
""")
            with open(os.path.join(cap_dir, 'plain.md'), 'w') as f:
                f.write("# No frontmatter\n")

            docs = find_anchored_docs(tmpdir)
            self.assertEqual(len(docs), 1)
            self.assertEqual(docs[0].capability, 'notifications')


if __name__ == '__main__':
    unittest.main()
