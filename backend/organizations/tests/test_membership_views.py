import threading

from django.contrib.auth.models import User
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from organizations.exceptions import LastOwnerError
from organizations.models import Organization, OrganizationMembership
from organizations.views import _assert_not_last_owner


def _membership_url(organization_id, membership_id):
    return reverse(
        'membership-detail', kwargs={'organization_id': organization_id, 'membership_id': membership_id},
    )


class ChangeMemberRoleTests(TestCase):
    def test_owner_can_change_another_members_role(self):
        owner = User.objects.create_user(username='owner', password='pw')
        member = User.objects.create_user(username='member', password='pw')
        org = Organization.objects.create(name='Acme')
        OrganizationMembership.objects.create(organization=org, user=owner, role='owner')
        membership = OrganizationMembership.objects.create(organization=org, user=member, role='member')
        self.client.force_login(owner)

        response = self.client.patch(
            _membership_url(org.id, membership.id), {'role': 'admin'}, content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        membership.refresh_from_db()
        self.assertEqual(membership.role, 'admin')

    def test_admin_cannot_change_roles(self):
        admin = User.objects.create_user(username='admin', password='pw')
        member = User.objects.create_user(username='member', password='pw')
        org = Organization.objects.create(name='Acme')
        OrganizationMembership.objects.create(organization=org, user=admin, role='admin')
        membership = OrganizationMembership.objects.create(organization=org, user=member, role='member')
        self.client.force_login(admin)

        response = self.client.patch(
            _membership_url(org.id, membership.id), {'role': 'admin'}, content_type='application/json',
        )

        self.assertEqual(response.status_code, 403)
        membership.refresh_from_db()
        self.assertEqual(membership.role, 'member')

    def test_member_cannot_change_roles(self):
        member = User.objects.create_user(username='member', password='pw')
        other = User.objects.create_user(username='other', password='pw')
        org = Organization.objects.create(name='Acme')
        OrganizationMembership.objects.create(organization=org, user=member, role='member')
        other_membership = OrganizationMembership.objects.create(organization=org, user=other, role='member')
        self.client.force_login(member)

        response = self.client.patch(
            _membership_url(org.id, other_membership.id), {'role': 'admin'}, content_type='application/json',
        )

        self.assertEqual(response.status_code, 403)

    def test_demoting_the_sole_owner_is_rejected(self):
        owner = User.objects.create_user(username='owner', password='pw')
        org = Organization.objects.create(name='Acme')
        membership = OrganizationMembership.objects.create(organization=org, user=owner, role='owner')
        self.client.force_login(owner)

        response = self.client.patch(
            _membership_url(org.id, membership.id), {'role': 'member'}, content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        membership.refresh_from_db()
        self.assertEqual(membership.role, 'owner')

    def test_demoting_one_of_two_owners_succeeds(self):
        owner_a = User.objects.create_user(username='owner_a', password='pw')
        owner_b = User.objects.create_user(username='owner_b', password='pw')
        org = Organization.objects.create(name='Acme')
        OrganizationMembership.objects.create(organization=org, user=owner_a, role='owner')
        membership_b = OrganizationMembership.objects.create(organization=org, user=owner_b, role='owner')
        self.client.force_login(owner_a)

        response = self.client.patch(
            _membership_url(org.id, membership_b.id), {'role': 'member'}, content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        membership_b.refresh_from_db()
        self.assertEqual(membership_b.role, 'member')

    def test_invalid_role_value_is_rejected(self):
        owner = User.objects.create_user(username='owner', password='pw')
        member = User.objects.create_user(username='member', password='pw')
        org = Organization.objects.create(name='Acme')
        OrganizationMembership.objects.create(organization=org, user=owner, role='owner')
        membership = OrganizationMembership.objects.create(organization=org, user=member, role='member')
        self.client.force_login(owner)

        response = self.client.patch(
            _membership_url(org.id, membership.id), {'role': 'superadmin'}, content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)


class RemoveMemberTests(TestCase):
    def test_owner_can_remove_a_member(self):
        owner = User.objects.create_user(username='owner', password='pw')
        member = User.objects.create_user(username='member', password='pw')
        org = Organization.objects.create(name='Acme')
        OrganizationMembership.objects.create(organization=org, user=owner, role='owner')
        membership = OrganizationMembership.objects.create(organization=org, user=member, role='member')
        self.client.force_login(owner)

        response = self.client.delete(_membership_url(org.id, membership.id))

        self.assertEqual(response.status_code, 204)
        self.assertFalse(OrganizationMembership.objects.filter(id=membership.id).exists())


class LastOwnerGuardLockScopeTests(TestCase):
    """Fast, deterministic, database-engine-independent test for the
    actual structural defect a fresh-session review caught:
    `_assert_not_last_owner` used to call `.exclude(id=exclude_membership_id)`
    on the SAME queryset that `.select_for_update()` locks, so the locked
    row set and the excluded row were coupled - two concurrent calls each
    excluding a DIFFERENT row (two different owners being mutated at once)
    would lock disjoint row sets and never contend, providing zero
    serialization between them.

    An outcome-based test (call it twice sequentially, check what it
    returns/raises) CANNOT distinguish the buggy version from the fixed
    one - both give identical answers for sequential, non-concurrent
    calls, since the exclude-before-count logic is correct in isolation;
    the bug only manifests when two calls's *lock acquisitions* overlap
    in time. (This was verified directly: an earlier draft of this test
    asserted only on return values/exceptions and passed unchanged against
    the reverted buggy code - a false negative. Kept a note here instead
    of silently fixing it without a trace.)

    What actually distinguishes the two versions is which rows the LOCK
    query's WHERE clause targets, independent of the exclude applied to
    the count. Assert on that directly, via the queryset's compiled SQL,
    rather than on an outcome that happens to coincide for both versions
    under single-threaded execution.
    """

    def test_lock_query_covers_every_owner_row_not_just_the_non_excluded_ones(self):
        org = Organization.objects.create(name='Acme')
        owner_a = User.objects.create_user(username='lock-owner-a', password='pw')
        owner_b = User.objects.create_user(username='lock-owner-b', password='pw')
        membership_a = OrganizationMembership.objects.create(organization=org, user=owner_a, role='owner')
        membership_b = OrganizationMembership.objects.create(organization=org, user=owner_b, role='owner')

        # Capture the ACTUAL SQL _assert_not_last_owner itself issues (not
        # a reconstructed query of our own, which would test nothing about
        # the real function) and assert the locked/counted query's WHERE
        # clause does not filter out either owner's id. The buggy version
        # chained .exclude(id=exclude_membership_id) directly onto the
        # select_for_update()'d queryset, so its SQL contains a
        # `NOT (... id = <value>)` clause narrowing the locked set itself;
        # the fix locks the full owner set unconditionally and applies the
        # exclude only to the in-memory id list afterward, so the emitted
        # SQL has no such clause at all.
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with self.settings(DEBUG=True), CaptureQueriesContext(connection) as ctx:
            _assert_not_last_owner(org.id, exclude_membership_id=membership_a.id)

        lock_queries = [q['sql'] for q in ctx.captured_queries if 'organizations_organizationmembership' in q['sql'].lower()]
        self.assertTrue(lock_queries, 'expected _assert_not_last_owner to issue at least one query against OrganizationMembership')
        for sql in lock_queries:
            self.assertNotIn(
                'NOT', sql.upper(),
                f"the lock/count query must not exclude any row by id - exclude belongs only in the "
                f"in-memory count after the full owner set is locked, never in the locked queryset "
                f"itself (two concurrent calls excluding different rows would then lock disjoint, "
                f"non-contending sets). Query was: {sql}",
            )

        # Behavioral sanity check (not the primary assertion - see
        # docstring on why outcome alone can't catch the real bug): still
        # correct with two owners present, and still raises once only one
        # remains.
        membership_a.role = 'member'
        membership_a.save(update_fields=['role'])
        with self.assertRaises(LastOwnerError):
            _assert_not_last_owner(org.id, exclude_membership_id=membership_b.id)


class LastOwnerGuardConcurrencyTests(TransactionTestCase):
    """Threaded regression test for the same TOCTOU race described above.

    Uses TransactionTestCase (not TestCase) for the same reason as
    runs/tests/test_views.py's ConcurrentUploadTests: TestCase wraps each
    test in a transaction that rolls back at the end, which would hide a
    real cross-thread transaction interaction.

    Known limitation (confirmed during review, do not "fix" by assuming
    this test alone is sufficient): SQLite has NO real row-level locking -
    select_for_update() silently compiles to a plain SELECT with no FOR
    UPDATE clause at all on this backend. Any apparent protection this
    test shows on SQLite comes from SQLite's own incidental single-writer
    serialization of the underlying UPDATE statements, not from anything
    the application does - a build with the lock removed entirely still
    passes this test on SQLite. The real regression coverage for the
    locking logic itself is LastOwnerGuardLockScopeTests above; this test
    is kept as a realistic end-to-end exercise of the HTTP-level flow, and
    was independently verified against real Postgres (10/10 trials safe
    post-fix, 10/10 trials reproduced the zero-owner bug pre-fix) during
    this story's review - see PR #38. See also issue #34 for the same
    SQLite-concurrency caveat on this codebase's other concurrent-write
    test.
    """

    def test_concurrent_demotion_of_both_owners_rejects_exactly_one(self):
        owner_a = User.objects.create_user(username='owner-a', password='pw')
        owner_b = User.objects.create_user(username='owner-b', password='pw')
        org = Organization.objects.create(name='Acme')
        membership_a = OrganizationMembership.objects.create(organization=org, user=owner_a, role='owner')
        membership_b = OrganizationMembership.objects.create(organization=org, user=owner_b, role='owner')

        results = []
        results_lock = threading.Lock()

        def demote(acting_user, target_membership):
            from django.test import Client
            try:
                client = Client()
                client.force_login(acting_user)
                response = client.patch(
                    _membership_url(org.id, target_membership.id),
                    {'role': 'member'},
                    content_type='application/json',
                )
                status = response.status_code
            except Exception as e:
                status = f'error: {e!r}'
            with results_lock:
                results.append(status)

        threads = [
            threading.Thread(target=demote, args=(owner_a, membership_b)),
            threading.Thread(target=demote, args=(owner_b, membership_a)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        successes = [r for r in results if r == 200]
        self.assertLessEqual(
            len(successes), 1,
            f'at most one of the two concurrent demotions may succeed, got {results}',
        )
        remaining_owners = OrganizationMembership.objects.filter(organization_id=org.id, role='owner').count()
        self.assertGreaterEqual(remaining_owners, 1, 'organization must never end up with zero owners')

    def test_admin_cannot_remove_members(self):
        admin = User.objects.create_user(username='admin', password='pw')
        member = User.objects.create_user(username='member', password='pw')
        org = Organization.objects.create(name='Acme')
        OrganizationMembership.objects.create(organization=org, user=admin, role='admin')
        membership = OrganizationMembership.objects.create(organization=org, user=member, role='member')
        self.client.force_login(admin)

        response = self.client.delete(_membership_url(org.id, membership.id))

        self.assertEqual(response.status_code, 403)
        self.assertTrue(OrganizationMembership.objects.filter(id=membership.id).exists())

    def test_removing_the_sole_owner_is_rejected(self):
        owner = User.objects.create_user(username='owner', password='pw')
        org = Organization.objects.create(name='Acme')
        membership = OrganizationMembership.objects.create(organization=org, user=owner, role='owner')
        self.client.force_login(owner)

        response = self.client.delete(_membership_url(org.id, membership.id))

        self.assertEqual(response.status_code, 400)
        self.assertTrue(OrganizationMembership.objects.filter(id=membership.id).exists())

    def test_removing_one_of_two_owners_succeeds(self):
        owner_a = User.objects.create_user(username='owner_a', password='pw')
        owner_b = User.objects.create_user(username='owner_b', password='pw')
        org = Organization.objects.create(name='Acme')
        OrganizationMembership.objects.create(organization=org, user=owner_a, role='owner')
        membership_b = OrganizationMembership.objects.create(organization=org, user=owner_b, role='owner')
        self.client.force_login(owner_a)

        response = self.client.delete(_membership_url(org.id, membership_b.id))

        self.assertEqual(response.status_code, 204)
        self.assertFalse(OrganizationMembership.objects.filter(id=membership_b.id).exists())

    def test_cross_org_membership_id_gets_404(self):
        owner = User.objects.create_user(username='owner', password='pw')
        other_member = User.objects.create_user(username='other', password='pw')
        org = Organization.objects.create(name='Acme')
        other_org = Organization.objects.create(name='Other Co')
        OrganizationMembership.objects.create(organization=org, user=owner, role='owner')
        other_membership = OrganizationMembership.objects.create(
            organization=other_org, user=other_member, role='member',
        )
        self.client.force_login(owner)

        response = self.client.delete(_membership_url(org.id, other_membership.id))

        self.assertEqual(response.status_code, 404)
        self.assertTrue(OrganizationMembership.objects.filter(id=other_membership.id).exists())
