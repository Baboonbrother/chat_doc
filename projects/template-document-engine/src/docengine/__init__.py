"""docengine｜範本導向文件生成引擎的套件根。

io: 無（僅匯出版本與套件常數）
依賴: 無
"""

__version__ = "0.1.0.dev0"

#: Document IR / Template Profile / Canonical Data 三個核心契約的 schema 版本。
#: 契約破壞性變更時必須遞增，並在 DECISIONS.md 留下決策紀錄。
CONTRACT_SCHEMA_VERSION = "1.0"

__all__ = ["__version__", "CONTRACT_SCHEMA_VERSION"]
