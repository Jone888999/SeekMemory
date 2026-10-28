"""Local persona files; authored seeds never become chat evidence."""
from __future__ import annotations

import json
import os
import tempfile
import re
from pathlib import Path

from ..core.persona import normalize_persona_file

ID = re.compile(r'^[a-z0-9][a-z0-9_.-]{1,63}$')
MAX_BYTES = 65536


class FilePersonaPacks:
    def __init__(self, official: Path, personal: Path) -> None:
        self.official = official
        self.personal = personal

    def _path(self, reference: str) -> Path:
        parts = reference.split('/')
        if len(parts) != 2 or parts[0] not in {'official', 'mine'} or not ID.fullmatch(parts[1]):
            raise ValueError('人格包标识无效')
        root = self.official if parts[0] == 'official' else self.personal
        path = root / parts[1] / 'persona.json' if parts[0] == 'official' else root / (parts[1] + '.json')
        if root.is_symlink() or path.parent.is_symlink() or path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError('人格包不允许符号链接或目录穿越')
        return path

    @staticmethod
    def _read_json(path: Path) -> object:
        if not path.is_file():
            raise LookupError('人格包不存在')
        if path.stat().st_size > MAX_BYTES:
            raise ValueError('人格文件过大')
        with path.open('rb') as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError('人格文件过大')
        return json.loads(raw.decode('utf-8'))

    def read(self, reference: str) -> dict:
        seed = normalize_persona_file(self._read_json(self._path(reference)))
        if seed['id'] != reference.split('/')[1]:
            raise ValueError('人格包目录与文件 id 不一致')
        # Empty corpus is not a valid authored corpus in the canonical format.
        if not seed['corpus']:
            seed.pop('corpus')
        return seed

    def catalog(self, collection: str, offset: int = 0, limit: int = 24) -> dict:
        if collection not in {'official', 'mine'} or not 0 <= offset <= 100000 or not 1 <= limit <= 100:
            raise ValueError('目录分页参数无效')
        if collection == 'official':
            index = self.official / 'index.json'
            if index.is_symlink():
                raise ValueError('目录索引不允许符号链接')
            ids = self._read_json(index)
            if not isinstance(ids, list) or any(not isinstance(i, str) or not ID.fullmatch(i) for i in ids) or len(set(ids)) != len(ids):
                raise ValueError('人格包目录索引无效')
        else:
            if self.personal.is_symlink():
                raise ValueError('个人目录不允许符号链接')
            ids = sorted(p.stem for p in self.personal.glob('*.json'))
        items = []
        for seed_id in ids[offset:offset + limit]:
            reference = f'{collection}/{seed_id}'
            seed = self.read(reference)
            items.append({
                'reference': reference, 'id': seed['id'], 'name': seed['name'],
                'version': seed['version'], 'description': seed['persona'][:120],
                'license': seed['license'], 'source': seed['source'],
                'contentRating': seed['content_rating'], 'locale': seed['locale'],
            })
        return {'items': items, 'total': len(ids), 'offset': offset, 'limit': limit}

    def save(self, raw: dict, expected_version: str | None = None) -> str:
        seed = normalize_persona_file(raw)
        if not seed['corpus']:
            seed.pop('corpus')
        reference = f"mine/{seed['id']}"
        path = self._path(reference)
        if expected_version is not None:
            previous = self.read(reference)
            if previous['version'] != expected_version or seed['version'] == expected_version:
                raise ValueError('人格包版本已变化，或新文件尚未提高版本号')
        encoded = json.dumps(seed, ensure_ascii=False, indent=2).encode('utf-8')
        if len(encoded) > MAX_BYTES:
            raise ValueError('人格文件过大')
        path.parent.mkdir(parents=True, exist_ok=True)
        # Publish only a complete file, without overwriting a concurrent import.
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.import-', delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            if expected_version is None:
                os.link(temporary, path)
            else:
                # Keep the old blueprint recoverable before atomically publishing the update.
                trash = self.personal / '.trash'
                if trash.is_symlink():
                    raise ValueError('回收目录无效')
                trash.mkdir(exist_ok=True)
                from uuid import uuid4
                os.link(path, trash / f'{path.stem}-{uuid4().hex}.json')
                os.replace(temporary, path)
        except FileExistsError as exc:
            raise ValueError('同名人格包已存在，请使用新的 id') from exc
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return reference

    def remove(self, reference: str) -> None:
        if not reference.startswith('mine/'):
            raise ValueError('内置人格包不可移除')
        path = self._path(reference)
        if not path.exists():
            raise LookupError('人格包不存在')
        # Keep a recoverable local copy. Removing a pack never changes active persona.
        trash = self.personal / '.trash'
        if trash.is_symlink():
            raise ValueError('回收目录无效')
        trash.mkdir(exist_ok=True)
        from uuid import uuid4
        path.rename(trash / f'{path.stem}-{uuid4().hex}.json')
