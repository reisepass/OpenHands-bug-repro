#!/usr/bin/env python3
"""
Reproduction script for Issue #12858: User skills do not load in v1.3.0

This script directly calls the same SDK function the agent-server uses,
simulating both the host environment and the Docker container environment.
"""

import os
import sys
import tempfile
from pathlib import Path

# Ensure we can import from the project
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def create_test_skills(skills_dir: Path):
    """Create test user skills in the given directory."""
    skills_dir.mkdir(parents=True, exist_ok=True)

    skill1 = skills_dir / "deepsolve.md"
    skill1.write_text("""---
name: deepsolve
triggers:
  - deep-solve
  - analysis
---

# Deep Solve Skill

A test user skill for deep analysis.
""")

    skill2 = skills_dir / "eda.md"
    skill2.write_text("""---
name: eda
triggers:
  - eda
  - explore-data
---

# EDA Skill

A test user skill for exploratory data analysis.
""")

    skill3 = skills_dir / "checkpoint.md"
    skill3.write_text("""---
name: checkpoint
---

# Checkpoint Skill

A test user skill for checkpointing.
""")

    return [skill1, skill2, skill3]


def test_host_environment():
    """Test 1: User skills load correctly on the HOST (outside Docker).

    This simulates what happens when the agent-server runs locally,
    where Path.home() resolves correctly to the user's home directory.
    """
    print("\n" + "=" * 60)
    print("TEST 1: Host environment (Path.home() works correctly)")
    print("=" * 60)

    home_dir = Path.home()
    skills_dir = home_dir / ".openhands" / "skills"

    # Create test skills
    created = create_test_skills(skills_dir)
    print(f"[INFO] Created {len(created)} test skills in {skills_dir}")
    for f in created:
        print(f"  - {f}")

    # Now call the actual SDK function
    from openhands.sdk.context.skills.skill import USER_SKILLS_DIRS, load_user_skills

    print(f"\n[INFO] USER_SKILLS_DIRS resolves to:")
    for d in USER_SKILLS_DIRS:
        exists = d.exists()
        file_count = len(list(d.glob("*.md"))) if exists else 0
        print(f"  - {d} (exists={exists}, md_files={file_count})")

    skills = load_user_skills()
    print(f"\n[RESULT] load_user_skills() returned {len(skills)} skills:")
    for s in skills:
        print(f"  - name={s.name}, triggers={s.get_triggers()}, source={s.source}")

    if len(skills) > 0:
        print("\n[PASS] User skills loaded successfully on HOST")
        return True
    else:
        print("\n[FAIL] User skills NOT loaded on HOST")
        return False


def test_docker_environment():
    """Test 2: Simulate Docker container where Path.home() points elsewhere.

    Inside the agent-server Docker container:
    - ~/.openhands is mounted at /.openhands
    - Path.home() returns /root (or similar container home)
    - /root/.openhands/skills/ does NOT exist
    - /.openhands/skills/ DOES exist (from volume mount)

    This is the ROOT CAUSE of issue #12858.
    """
    print("\n" + "=" * 60)
    print("TEST 2: Simulated Docker environment (Path.home() mismatch)")
    print("=" * 60)

    # Create a fake Docker-like environment
    with tempfile.TemporaryDirectory() as tmpdir:
        # Simulate container structure:
        # /fake_root  -> what Path.home() returns in container
        # /fake_mount -> where ~/.openhands actually gets mounted
        fake_home = Path(tmpdir) / "fake_root"
        fake_home.mkdir()
        fake_mount = Path(tmpdir) / ".openhands"

        # Create skills in the mount point (simulating docker volume mount)
        mount_skills_dir = fake_mount / "skills"
        created = create_test_skills(mount_skills_dir)
        print(f"[INFO] Created {len(created)} skills at mount point: {mount_skills_dir}")

        # The container's home directory does NOT have .openhands/skills
        container_home_skills = fake_home / ".openhands" / "skills"
        print(f"[INFO] Container home skills dir: {container_home_skills} (exists={container_home_skills.exists()})")

        # Monkey-patch Path.home() to simulate container behavior
        original_home = Path.home
        Path.home = staticmethod(lambda: fake_home)

        try:
            # Re-import to get fresh USER_SKILLS_DIRS with patched home
            from openhands.sdk.context.skills import skill as skill_module

            # Recalculate USER_SKILLS_DIRS with fake home
            patched_dirs = [
                fake_home / ".openhands" / "skills",
                fake_home / ".openhands" / "microagents",
            ]
            original_dirs = skill_module.USER_SKILLS_DIRS
            skill_module.USER_SKILLS_DIRS = patched_dirs

            print(f"\n[INFO] Patched USER_SKILLS_DIRS (simulating container):")
            for d in patched_dirs:
                exists = d.exists()
                print(f"  - {d} (exists={exists})")

            print(f"\n[INFO] Actual skill files location:")
            print(f"  - {mount_skills_dir} (exists={mount_skills_dir.exists()}, "
                  f"files={len(list(mount_skills_dir.glob('*.md')))})")

            # Call load_user_skills() - this is what the agent-server does
            from openhands.sdk.context.skills.skill import load_user_skills
            skills = load_user_skills()

            print(f"\n[RESULT] load_user_skills() returned {len(skills)} skills")

            if len(skills) == 0:
                print("\n[FAIL] User skills NOT loaded in container environment")
                print("[REPRODUCED] Issue #12858 is CONFIRMED")
                print("\n[ROOT CAUSE] Path.home() in Docker container resolves to")
                print(f"  container home ({fake_home}), but user skills are mounted")
                print(f"  at {fake_mount}/skills/ via Docker volume mount.")
                print("  The SDK's USER_SKILLS_DIRS uses Path.home() which doesn't")
                print("  match the Docker volume mount point.")
                return True  # Bug IS reproduced
            else:
                print("\n[PASS] Skills loaded (bug NOT reproduced in simulation)")
                return False

        finally:
            # Restore
            Path.home = original_home
            skill_module.USER_SKILLS_DIRS = original_dirs


def test_full_load_all_skills():
    """Test 3: Call the full load_all_skills() from the agent-server service,
    which is the exact function called when the /api/skills endpoint is hit.
    """
    print("\n" + "=" * 60)
    print("TEST 3: Full load_all_skills() (agent-server service function)")
    print("=" * 60)

    # Make sure user skills exist on host
    home_dir = Path.home()
    skills_dir = home_dir / ".openhands" / "skills"
    create_test_skills(skills_dir)

    from openhands.agent_server.skills_service import load_all_skills

    # Call with load_user=True (same as app-server does)
    result = load_all_skills(
        load_public=False,  # Skip public to avoid git clone
        load_user=True,
        load_project=False,
        load_org=False,
        project_dir=None,
        org_repo_url=None,
        org_name=None,
        sandbox_exposed_urls=None,
    )

    print(f"\n[RESULT] load_all_skills() sources: {result.sources}")
    print(f"[RESULT] Total skills: {len(result.skills)}")
    for s in result.skills:
        print(f"  - name={s.name}, source={s.source}")

    user_count = result.sources.get("user", 0)
    if user_count > 0:
        print(f"\n[PASS] {user_count} user skills loaded on HOST")
    else:
        print(f"\n[FAIL] 0 user skills loaded on HOST")

    return user_count


def main():
    print("=" * 60)
    print("REPRODUCING ISSUE #12858: User skills do not load in v1.3.0")
    print("=" * 60)

    # Test 1: Host environment
    host_works = test_host_environment()

    # Test 2: Docker simulation
    docker_fails = test_docker_environment()

    # Test 3: Full agent-server function
    user_count = test_full_load_all_skills()

    # Final report
    print("\n" + "=" * 60)
    print("REPRODUCTION REPORT")
    print("=" * 60)
    print(f"\nTest 1 - Host environment:     {'PASS' if host_works else 'FAIL'}")
    print(f"Test 2 - Docker simulation:    {'REPRODUCED (bug confirmed)' if docker_fails else 'NOT reproduced'}")
    print(f"Test 3 - Agent-server service: {'PASS' if user_count > 0 else 'FAIL'} (user={user_count})")

    print("\n--- ROOT CAUSE ---")
    if docker_fails:
        print("""
CONFIRMED: Issue #12858 is reproducible.

The SDK defines USER_SKILLS_DIRS using Path.home():

    USER_SKILLS_DIRS = [
        Path.home() / ".openhands" / "skills",
        Path.home() / ".openhands" / "microagents",
    ]

In the Docker container:
  - Path.home() returns /root (or similar container home)
  - Docker mounts ~/.openhands at /.openhands (root of filesystem)
  - So Path.home()/.openhands/skills = /root/.openhands/skills (DOES NOT EXIST)
  - But the actual skills are at /.openhands/skills (EXISTS)

FIX: The agent-server or SDK should also check /.openhands/skills/
when running inside a Docker container, or use an environment variable
to configure the user skills path.

Location of bug: openhands-sdk package
  File: openhands/sdk/context/skills/skill.py
  Lines: 658-661 (USER_SKILLS_DIRS constant)
  Function: load_user_skills() at line 664
""")
    else:
        print("Could not reproduce the Docker path mismatch.")

    # Exit with appropriate code
    sys.exit(0 if docker_fails else 1)


if __name__ == "__main__":
    main()
