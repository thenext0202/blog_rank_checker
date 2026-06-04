# -*- coding: utf-8 -*-
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sheets import parse_targets


def test_parse_targets_체크된행만():
    rows = [
        ["키워드","실행","인기글"],          # 1행 헤더
        ["오메가3 영양제","TRUE",""],          # 2행 체크됨
        ["콘드로이친","FALSE",""],             # 3행 미체크
        ["고혈압 수치","TRUE",""],             # 4행 체크됨
        ["","",""],                            # 5행 빈 행
    ]
    assert parse_targets(rows) == [(2, "오메가3 영양제"), (4, "고혈압 수치")]


def test_parse_targets_키워드없으면_제외():
    rows = [["키워드","실행"], ["","TRUE"]]
    assert parse_targets(rows) == []
