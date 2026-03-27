#!/usr/bin/env python3
from __future__ import annotations

import json
from index_store import rebuild_registry, REG_PATH

if __name__ == '__main__':
    reg = rebuild_registry()
    print(json.dumps({'ok': True, 'registry': str(REG_PATH), 'counts': reg.get('counts', {})}, indent=2))
