from dataclasses import dataclass
from typing import Optional, List
from dataclasses_json import dataclass_json
from datetime import datetime

@dataclass_json
@dataclass
class SPRTResults:
    """Statistics from an LLR (Log Likelihood Ratio) test"""
    llr: float
    lower_bound: float
    upper_bound: float
    elo0: float
    elo1: float
    pentanomial: list[int]
    wins: int
    losses: int
    draws: int

@dataclass_json
@dataclass
class FileContent:
    filepath: str
    content: Optional[str]

@dataclass_json
@dataclass
class TestEntry:
    user: str
    engine: str
    testname: str
    url: str
    time_control: str
    statblock: str
    base_hash: str = ""
    new_hash: str = ""
    results: Optional[SPRTResults] = None
    date: Optional[datetime] = None
    exists: bool = False
    git_diff: Optional[str] = None
    old_file_versions: Optional[List[FileContent]] = None
    new_file_versions: Optional[List[FileContent]] = None


@dataclass_json
@dataclass
class RunEntryList:
    list: List[TestEntry]
