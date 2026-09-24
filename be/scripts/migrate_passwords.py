"""레거시 평문 비밀번호 일괄 마이그레이션 CLI 스크립트.

DB 내의 User 테이블을 배치 단위로 조회하여,
bcrypt / bcrypt-sha256 해시가 적용되지 않은 평문 비밀번호를 안전하게 단방향 해시로 변환합니다.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

# Add 'be' to sys.path so imports work regardless of invocation cwd
BE_DIR = Path(__file__).resolve().parent.parent
if str(BE_DIR) not in sys.path:
    sys.path.insert(0, str(BE_DIR))

from db.session import SessionLocal
from models.user.user import User
from security import hash_password, password_needs_upgrade

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("migrate_passwords")


def migrate_passwords(batch_size: int = 100, dry_run: bool = False) -> dict[str, int]:
    """레거시 비밀번호 일괄 마이그레이션을 실행합니다."""
    stats = {
        "total_scanned": 0,
        "already_hashed": 0,
        "migrated": 0,
        "failed": 0,
    }

    db = SessionLocal()
    try:
        last_id = 0
        logger.info(
            f"비밀번호 마이그레이션 시작 (배치 크기: {batch_size}, dry_run: {dry_run})"
        )

        while True:
            users = (
                db.query(User)
                .filter(User.user_id > last_id)
                .order_by(User.user_id.asc())
                .limit(batch_size)
                .all()
            )
            if not users:
                break

            for user in users:
                stats["total_scanned"] += 1
                last_id = user.user_id
                stored_pw = user.password or ""

                if not password_needs_upgrade(stored_pw):
                    stats["already_hashed"] += 1
                    continue

                if dry_run:
                    stats["migrated"] += 1
                    logger.info(f"[DRY-RUN] User ID {user.user_id} ({user.id}) 비밀번호 마이그레이션 대상")
                else:
                    try:
                        user.password = hash_password(stored_pw)
                        stats["migrated"] += 1
                    except Exception as e:
                        stats["failed"] += 1
                        logger.error(
                            f"User ID {user.user_id} ({user.id}) 해시 변환 실패: {e}"
                        )

            if not dry_run:
                try:
                    db.commit()
                    logger.info(
                        f"배치 커밋 완료 (현재까지 검사: {stats['total_scanned']}, 마이그레이션: {stats['migrated']})"
                    )
                except Exception as e:
                    db.rollback()
                    logger.error(f"배치 커밋 실패: {e}")
                    raise

        logger.info("=" * 50)
        logger.info(f"마이그레이션 완료 결과:")
        logger.info(f" - 총 스캔 계정 수: {stats['total_scanned']}")
        logger.info(f" - 이미 해시된 계정 수: {stats['already_hashed']}")
        logger.info(f" - 마이그레이션된 계정 수: {stats['migrated']}")
        logger.info(f" - 실패한 계정 수: {stats['failed']}")
        logger.info("=" * 50)
        return stats

    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description="레거시 평문 비밀번호 일괄 마이그레이션")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="한 번에 처리할 계정 수 (기본값: 100)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="실제 DB에 반영하지 않고 마이그레이션 대상만 확인",
    )
    args = parser.parse_args()

    migrate_passwords(batch_size=args.batch_size, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
