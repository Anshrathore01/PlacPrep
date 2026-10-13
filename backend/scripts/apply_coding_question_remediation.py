"""Apply only individually specified and Docker-verified coding repairs."""

from __future__ import annotations

import csv
import json
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import engine
from app.judge.docker_sandbox import docker_is_ready, execute_submission
from app.services import question_governance_service


BACKEND = Path(__file__).resolve().parents[1]
REPORTS = BACKEND / "reports"
BEFORE_JSON = REPORTS / "coding_290_before_apply.json"
RESULT_JSON = REPORTS / "coding_290_remediation_result.json"
RESULT_CSV = REPORTS / "coding_290_remediation_result.csv"
RESULT_MD = REPORTS / "coding_290_remediation_result.md"
REVIEW_MARKER = "CODING_290_PRODUCTION_REMEDIATION:v1:"
EXPECTED_COUNT = 290
REVIEWER_ID = 7
BATCH_SIZE = 20

SPECS = {
    1: {
        "input_format": "The first line contains N. The second line contains N space-separated integers arr[i].",
        "output_format": "Print the N array elements in reversed order, separated by single spaces, on one line.",
        "time": "O(N)",
        "space": "O(1) auxiliary space",
        "explanation": "Reverse the sequence by exchanging symmetric elements from the two ends until the pointers meet.",
        "reference": r"""
#include <iostream>
#include <vector>
#include <algorithm>
int main(){std::ios::sync_with_stdio(false);std::cin.tie(nullptr);int n;if(!(std::cin>>n))return 0;std::vector<long long>a(n);for(auto&x:a)std::cin>>x;std::reverse(a.begin(),a.end());for(int i=0;i<n;i++){if(i)std::cout<<' ';std::cout<<a[i];}std::cout<<'\n';}
""",
        "starter": r"""
#include <iostream>
#include <vector>
int main(){std::ios::sync_with_stdio(false);std::cin.tie(nullptr);int n;if(!(std::cin>>n))return 0;std::vector<long long> arr(n);for(auto& value:arr)std::cin>>value;
    // TODO: reverse arr in place and print its elements.
}
""",
        "cases": [
            ("5\n1 2 3 4 5\n", "5 4 3 2 1\n", False),
            ("1\n7\n", "7\n", False),
            ("2\n-1 9\n", "9 -1\n", True),
            ("4\n1 1 2 2\n", "2 2 1 1\n", True),
            ("5\n5 4 3 2 1\n", "1 2 3 4 5\n", True),
            ("3\n0 -1000000000 1000000000\n", "1000000000 -1000000000 0\n", True),
            ("6\n8 0 -3 5 2 1\n", "1 2 5 -3 0 8\n", True),
        ],
    },
    3: {
        "input_format": "The first line contains N. The second line contains N space-separated integers arr[i].",
        "output_format": "Print the array after moving all zero values to the end while preserving the order of non-zero values, separated by single spaces.",
        "time": "O(N)",
        "space": "O(1) auxiliary space",
        "explanation": "Scan from left to right and compact non-zero elements into the next write position. Fill the remaining positions with zero.",
        "reference": r"""
#include <iostream>
#include <vector>
int main(){std::ios::sync_with_stdio(false);std::cin.tie(nullptr);int n;if(!(std::cin>>n))return 0;std::vector<long long>a(n);for(auto&x:a)std::cin>>x;int w=0;for(long long x:a)if(x!=0)a[w++]=x;while(w<n)a[w++]=0;for(int i=0;i<n;i++){if(i)std::cout<<' ';std::cout<<a[i];}std::cout<<'\n';}
""",
        "starter": r"""
#include <iostream>
#include <vector>
int main(){std::ios::sync_with_stdio(false);std::cin.tie(nullptr);int n;if(!(std::cin>>n))return 0;std::vector<long long> arr(n);for(auto& value:arr)std::cin>>value;
    // TODO: move zeros to the end in place, preserving non-zero order, and print arr.
}
""",
        "cases": [
            ("5\n0 1 0 3 12\n", "1 3 12 0 0\n", False),
            ("3\n1 2 3\n", "1 2 3\n", False),
            ("1\n0\n", "0\n", True),
            ("4\n0 0 0 0\n", "0 0 0 0\n", True),
            ("5\n-1 0 2 0 -3\n", "-1 2 -3 0 0\n", True),
            ("6\n0 4 0 5 6 0\n", "4 5 6 0 0 0\n", True),
            ("4\n2 0 2 0\n", "2 2 0 0\n", True),
        ],
    },
    4: {
        "input_format": "The first line contains N, the length of nums. The second line contains N distinct space-separated integers in [0, N].",
        "output_format": "Print the missing integer in [0, N].",
        "time": "O(N)",
        "space": "O(1) auxiliary space",
        "explanation": "XOR all values from zero through N with the supplied array values; each present value cancels, leaving the missing value.",
        "reference": r"""
#include <iostream>
#include <vector>
int main(){std::ios::sync_with_stdio(false);std::cin.tie(nullptr);int n;if(!(std::cin>>n))return 0;int answer=0;for(int i=0;i<=n;i++)answer^=i;for(int i=0,x;i<n;i++){std::cin>>x;answer^=x;}std::cout<<answer<<'\n';}
""",
        "starter": r"""
#include <iostream>
#include <vector>
int main(){std::ios::sync_with_stdio(false);std::cin.tie(nullptr);int n;if(!(std::cin>>n))return 0;std::vector<int> nums(n);for(int& value:nums)std::cin>>value;
    // TODO: find and print the absent value from [0, N].
}
""",
        "cases": [
            ("3\n3 0 1\n", "2\n", False),
            ("2\n0 1\n", "2\n", False),
            ("1\n1\n", "0\n", True),
            ("1\n0\n", "1\n", True),
            ("3\n1 2 3\n", "0\n", True),
            ("5\n0 1 2 3 4\n", "5\n", True),
            ("6\n6 0 2 1 4 5\n", "3\n", True),
            ("4\n4 2 1 0\n", "3\n", True),
        ],
    },
    5: {
        "input_format": "The first line contains N. The second line contains N space-separated integers nums[i]; exactly one value occurs once and every other value occurs twice.",
        "output_format": "Print the single non-repeating integer.",
        "time": "O(N)",
        "space": "O(1) auxiliary space",
        "explanation": "XOR all values; equal pairs cancel, leaving the value that occurs once.",
        "reference": r"""
#include <iostream>
int main(){std::ios::sync_with_stdio(false);std::cin.tie(nullptr);int n;if(!(std::cin>>n))return 0;int answer=0;for(int i=0,x;i<n;i++){std::cin>>x;answer^=x;}std::cout<<answer<<'\n';}
""",
        "starter": r"""
#include <iostream>
int main(){std::ios::sync_with_stdio(false);std::cin.tie(nullptr);int n;if(!(std::cin>>n))return 0;int answer=0;for(int i=0,x;i<n;i++)std::cin>>x;
    // TODO: identify and print the value that occurs once.
}
""",
        "cases": [
            ("5\n2 2 1 1 3\n", "3\n", False),
            ("1\n7\n", "7\n", False),
            ("3\n-1 2 -1\n", "2\n", True),
            ("7\n4 1 2 1 2 4 9\n", "9\n", True),
            ("5\n0 8 0 8 -5\n", "-5\n", True),
            ("9\n12 3 12 4 3 5 4 7 7\n", "5\n", True),
            ("3\n-30000 30000 -30000\n", "30000\n", True),
        ],
    },
    6: {
        "input_format": "The first line contains N. The second line contains N space-separated integers nums[i].",
        "output_format": "Print the maximum sum of any non-empty contiguous subarray.",
        "time": "O(N)",
        "space": "O(1) auxiliary space",
        "explanation": "Kadane's recurrence keeps the best subarray ending at the current position and the best sum seen overall. Initializing from the first value handles all-negative arrays.",
        "reference": r"""
#include <iostream>
#include <algorithm>
int main(){std::ios::sync_with_stdio(false);std::cin.tie(nullptr);int n;if(!(std::cin>>n))return 0;long long x;std::cin>>x;long long current=x,best=x;for(int i=1;i<n;i++){std::cin>>x;current=std::max(x,current+x);best=std::max(best,current);}std::cout<<best<<'\n';}
""",
        "starter": r"""
#include <iostream>
int main(){std::ios::sync_with_stdio(false);std::cin.tie(nullptr);int n;if(!(std::cin>>n))return 0;long long value;for(int i=0;i<n;i++)std::cin>>value;
    // TODO: compute and print the maximum non-empty contiguous-subarray sum.
}
""",
        "cases": [
            ("9\n-2 1 -3 4 -1 2 1 -5 4\n", "6\n", False),
            ("1\n5\n", "5\n", False),
            ("4\n-8 -3 -6 -2\n", "-2\n", True),
            ("5\n1 2 3 4 5\n", "15\n", True),
            ("5\n-2 -1 3 -4 5\n", "5\n", True),
            ("6\n0 -1 0 2 -1 2\n", "3\n", True),
            ("4\n10000 10000 10000 10000\n", "40000\n", True),
        ],
    },
    8: {
        "input_format": "The first line contains N. The second line contains N space-separated integers A[i].",
        "output_format": "Print all leaders in their original left-to-right order, separated by single spaces. The rightmost element is always a leader.",
        "time": "O(N)",
        "space": "O(N) for the returned leader sequence",
        "explanation": "Scan right to left while tracking the greatest value to the right. Keep a value only when it is strictly greater, then reverse the collected leaders to restore input order.",
        "reference": r"""
#include <iostream>
#include <vector>
#include <algorithm>
int main(){std::ios::sync_with_stdio(false);std::cin.tie(nullptr);int n;if(!(std::cin>>n))return 0;std::vector<long long>a(n),leaders;for(auto&x:a)std::cin>>x;long long mx=-1;for(int i=n-1;i>=0;i--)if(a[i]>mx){leaders.push_back(a[i]);mx=a[i];}std::reverse(leaders.begin(),leaders.end());for(size_t i=0;i<leaders.size();i++){if(i)std::cout<<' ';std::cout<<leaders[i];}std::cout<<'\n';}
""",
        "starter": r"""
#include <iostream>
#include <vector>
int main(){std::ios::sync_with_stdio(false);std::cin.tie(nullptr);int n;if(!(std::cin>>n))return 0;std::vector<long long> A(n);for(auto& value:A)std::cin>>value;
    // TODO: find the leaders and print them in their original order.
}
""",
        "cases": [
            ("6\n16 17 4 3 5 2\n", "17 5 2\n", False),
            ("1\n9\n", "9\n", False),
            ("4\n4 3 2 1\n", "4 3 2 1\n", True),
            ("4\n1 2 3 4\n", "4\n", True),
            ("3\n5 5 2\n", "5 2\n", True),
            ("5\n0 0 1 0 0\n", "1 0\n", True),
            ("5\n10 9 8 7 6\n", "10 9 8 7 6\n", True),
        ],
    },
    18: {
        "input_format": "The first line contains N. The second line contains N integers, each equal to 0, 1, or 2.",
        "output_format": "Print the sorted array as N space-separated integers on one line.",
        "time": "O(N)",
        "space": "O(1) auxiliary space",
        "explanation": "Maintain low, mid, and high boundaries for the three values. Swap zeroes to the front and twos to the back while advancing the unclassified region.",
        "reference": r"""
#include <iostream>
#include <vector>
#include <algorithm>
int main(){std::ios::sync_with_stdio(false);std::cin.tie(nullptr);int n;if(!(std::cin>>n))return 0;std::vector<int>a(n);for(int&x:a)std::cin>>x;int lo=0,mid=0,hi=n-1;while(mid<=hi){if(a[mid]==0)std::swap(a[lo++],a[mid++]);else if(a[mid]==1)mid++;else std::swap(a[mid],a[hi--]);}for(int i=0;i<n;i++){if(i)std::cout<<' ';std::cout<<a[i];}std::cout<<'\n';}
""",
        "starter": r"""
#include <iostream>
#include <vector>
int main(){std::ios::sync_with_stdio(false);std::cin.tie(nullptr);int n;if(!(std::cin>>n))return 0;std::vector<int> nums(n);for(int& value:nums)std::cin>>value;
    // TODO: sort the values in place in one pass and print nums.
}
""",
        "cases": [
            ("6\n2 0 2 1 1 0\n", "0 0 1 1 2 2\n", False),
            ("1\n0\n", "0\n", False),
            ("4\n2 2 2 2\n", "2 2 2 2\n", True),
            ("5\n1 1 1 0 0\n", "0 0 1 1 1\n", True),
            ("6\n0 1 2 0 1 2\n", "0 0 1 1 2 2\n", True),
            ("3\n2 1 0\n", "0 1 2\n", True),
            ("7\n1 2 0 1 2 0 1\n", "0 0 1 1 1 2 2\n", True),
        ],
    },
    21: {
        "input_format": "The first line contains N. The second line contains N space-separated non-negative bar heights.",
        "output_format": "Print the total number of unit-width water units trapped after raining.",
        "time": "O(N)",
        "space": "O(1) auxiliary space",
        "explanation": "Use two pointers and the maximum height seen from each side. The side with the lower current height determines trapped water that can be finalized.",
        "reference": r"""
#include <iostream>
#include <vector>
#include <algorithm>
int main(){std::ios::sync_with_stdio(false);std::cin.tie(nullptr);int n;if(!(std::cin>>n))return 0;std::vector<int>h(n);for(int&x:h)std::cin>>x;int l=0,r=n-1,lm=0,rm=0;long long total=0;while(l<=r){if(h[l]<=h[r]){lm=std::max(lm,h[l]);total+=lm-h[l];l++;}else{rm=std::max(rm,h[r]);total+=rm-h[r];r--;}}std::cout<<total<<'\n';}
""",
        "starter": r"""
#include <iostream>
#include <vector>
int main(){std::ios::sync_with_stdio(false);std::cin.tie(nullptr);int n;if(!(std::cin>>n))return 0;std::vector<int> height(n);for(int& value:height)std::cin>>value;
    // TODO: compute and print the total trapped water.
}
""",
        "cases": [
            ("12\n0 1 0 2 1 0 1 3 2 1 2 1\n", "6\n", False),
            ("1\n4\n", "0\n", False),
            ("4\n0 0 0 0\n", "0\n", True),
            ("5\n1 2 3 4 5\n", "0\n", True),
            ("5\n5 4 3 2 1\n", "0\n", True),
            ("3\n3 0 3\n", "3\n", True),
            ("6\n4 2 0 3 2 5\n", "9\n", True),
        ],
    },
    22: {
        "input_format": "The first line contains N. The second line contains N space-separated integers nums[i].",
        "output_format": "Print the lexicographically next permutation as N space-separated integers; if no greater permutation exists, print the lowest (ascending) permutation.",
        "time": "O(N)",
        "space": "O(1) auxiliary space",
        "explanation": "Find the rightmost ascent, exchange its left value with the smallest larger value in the suffix, then reverse the suffix. If no ascent exists, reverse the entire array.",
        "reference": r"""
#include <iostream>
#include <vector>
#include <algorithm>
int main(){std::ios::sync_with_stdio(false);std::cin.tie(nullptr);int n;if(!(std::cin>>n))return 0;std::vector<int>a(n);for(int&x:a)std::cin>>x;int i=n-2;while(i>=0&&a[i]>=a[i+1])i--;if(i>=0){int j=n-1;while(a[j]<=a[i])j--;std::swap(a[i],a[j]);}std::reverse(a.begin()+i+1,a.end());for(int k=0;k<n;k++){if(k)std::cout<<' ';std::cout<<a[k];}std::cout<<'\n';}
""",
        "starter": r"""
#include <iostream>
#include <vector>
int main(){std::ios::sync_with_stdio(false);std::cin.tie(nullptr);int n;if(!(std::cin>>n))return 0;std::vector<int> nums(n);for(int& value:nums)std::cin>>value;
    // TODO: transform nums to its lexicographically next permutation and print it.
}
""",
        "cases": [
            ("3\n1 2 3\n", "1 3 2\n", False),
            ("3\n3 2 1\n", "1 2 3\n", False),
            ("1\n1\n", "1\n", True),
            ("3\n1 1 5\n", "1 5 1\n", True),
            ("4\n1 3 2 4\n", "1 3 4 2\n", True),
            ("4\n2 2 3 1\n", "2 3 1 2\n", True),
            ("3\n0 100 99\n", "99 0 100\n", True),
        ],
    },
    23: {
        "input_format": "The first line contains N, the number of rows and columns. The next N lines each contain N space-separated matrix values.",
        "output_format": "Print the matrix after a 90-degree clockwise rotation, with one row per line and values separated by single spaces.",
        "time": "O(N^2)",
        "space": "O(1) auxiliary space",
        "explanation": "Transpose the square matrix across its main diagonal, then reverse each row; this produces a clockwise quarter-turn in place.",
        "reference": r"""
#include <iostream>
#include <vector>
#include <algorithm>
int main(){std::ios::sync_with_stdio(false);std::cin.tie(nullptr);int n;if(!(std::cin>>n))return 0;std::vector<std::vector<long long>>a(n,std::vector<long long>(n));for(auto&r:a)for(auto&x:r)std::cin>>x;for(int i=0;i<n;i++)for(int j=i+1;j<n;j++)std::swap(a[i][j],a[j][i]);for(auto&r:a){std::reverse(r.begin(),r.end());for(int j=0;j<n;j++){if(j)std::cout<<' ';std::cout<<r[j];}std::cout<<'\n';}}
""",
        "starter": r"""
#include <iostream>
#include <vector>
int main(){std::ios::sync_with_stdio(false);std::cin.tie(nullptr);int n;if(!(std::cin>>n))return 0;std::vector<std::vector<long long>> matrix(n,std::vector<long long>(n));for(auto& row:matrix)for(auto& value:row)std::cin>>value;
    // TODO: rotate matrix clockwise in place and print each row.
}
""",
        "cases": [
            ("3\n1 2 3\n4 5 6\n7 8 9\n", "7 4 1\n8 5 2\n9 6 3\n", False),
            ("1\n5\n", "5\n", False),
            ("2\n1 2\n3 4\n", "3 1\n4 2\n", True),
            ("3\n1 0 0\n0 1 0\n0 0 1\n", "0 0 1\n0 1 0\n1 0 0\n", True),
            ("2\n-1 2\n3 -4\n", "3 -1\n-4 2\n", True),
            ("4\n1 2 3 4\n5 6 7 8\n9 10 11 12\n13 14 15 16\n", "13 9 5 1\n14 10 6 2\n15 11 7 3\n16 12 8 4\n", True),
            ("3\n0 1 2\n3 4 5\n6 7 8\n", "6 3 0\n7 4 1\n8 5 2\n", True),
        ],
    },
    24: {
        "input_format": "The first line contains M and N. The next M lines each contain N space-separated matrix values.",
        "output_format": "Print the matrix elements in clockwise spiral order, separated by single spaces, on one line.",
        "time": "O(MN)",
        "space": "O(MN) for the returned traversal",
        "explanation": "Traverse the current top row, right column, bottom row, and left column, shrinking each boundary after traversal and checking that remaining rows or columns exist.",
        "reference": r"""
#include <iostream>
#include <vector>
int main(){std::ios::sync_with_stdio(false);std::cin.tie(nullptr);int m,n;if(!(std::cin>>m>>n))return 0;std::vector<std::vector<int>>a(m,std::vector<int>(n));for(auto&r:a)for(int&x:r)std::cin>>x;int t=0,b=m-1,l=0,r=n-1;std::vector<int>out;while(t<=b&&l<=r){for(int j=l;j<=r;j++)out.push_back(a[t][j]);t++;for(int i=t;i<=b;i++)out.push_back(a[i][r]);r--;if(t<=b){for(int j=r;j>=l;j--)out.push_back(a[b][j]);b--;}if(l<=r){for(int i=b;i>=t;i--)out.push_back(a[i][l]);l++;}}for(size_t i=0;i<out.size();i++){if(i)std::cout<<' ';std::cout<<out[i];}std::cout<<'\n';}
""",
        "starter": r"""
#include <iostream>
#include <vector>
int main(){std::ios::sync_with_stdio(false);std::cin.tie(nullptr);int m,n;if(!(std::cin>>m>>n))return 0;std::vector<std::vector<int>> matrix(m,std::vector<int>(n));for(auto& row:matrix)for(int& value:row)std::cin>>value;
    // TODO: print all matrix elements in clockwise spiral order.
}
""",
        "cases": [
            ("3 3\n1 2 3\n4 5 6\n7 8 9\n", "1 2 3 6 9 8 7 4 5\n", False),
            ("1 4\n1 2 3 4\n", "1 2 3 4\n", False),
            ("4 1\n1\n2\n3\n4\n", "1 2 3 4\n", True),
            ("2 2\n1 2\n3 4\n", "1 2 4 3\n", True),
            ("3 4\n1 2 3 4\n5 6 7 8\n9 10 11 12\n", "1 2 3 4 8 12 11 10 9 5 6 7\n", True),
            ("4 3\n1 2 3\n4 5 6\n7 8 9\n10 11 12\n", "1 2 3 6 9 12 11 10 7 4 5 8\n", True),
            ("1 1\n-5\n", "-5\n", True),
        ],
    },
}


def _json_default(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


def _source_evidence(question: dict) -> dict:
    return {
        "source_id": question.get("source_id"),
        "source_question_number": question.get("source_question_number"),
        "title": question.get("title"),
        "problem_statement": question.get("problem_statement"),
        "constraints": question.get("constraints_text"),
        "solution_pseudocode": question.get("solution_pseudocode"),
        "existing_input_format": question.get("input_format"),
        "existing_output_format": question.get("output_format"),
        "source_metadata": question.get("source_metadata"),
    }


def _reference_result(question_id: int, source: str, cases: list[dict]) -> dict:
    result = execute_submission(70_000_000 + question_id, source, cases)
    if result.get("status") != "PASSED" or result.get("tests_passed") != len(cases):
        raise RuntimeError(
            f"Reference validation failed for {question_id}: "
            f"{result.get('status')} {result.get('safe_error_message') or ''}"
        )
    return result


def _governance_check(connection, question_id: int) -> list[str]:
    return question_governance_service.validate_question_for_publication(
        connection, question_id
    )


def _record_for_review(connection, question: dict, reason: str) -> dict:
    question_id = int(question["question_id"])
    current = connection.execute(
        text("""
            SELECT question_type, status
            FROM questions
            WHERE question_id = :question_id
            FOR UPDATE
        """),
        {"question_id": question_id},
    ).mappings().one()
    if current["question_type"] != "CODING":
        raise RuntimeError(f"Question {question_id} is no longer a coding question.")
    marker = f"{REVIEW_MARKER}{question_id}"
    already_logged = connection.execute(
        text("""
            SELECT review_id
            FROM question_reviews
            WHERE question_id = :question_id
              AND LEFT(notes, CHAR_LENGTH(:marker)) = :marker
            LIMIT 1
        """),
        {"question_id": question_id, "marker": marker},
    ).scalar_one_or_none()
    if current["status"] == "DRAFT":
        question_governance_service.transition_question_status(
            connection,
            question_id,
            "REVIEW",
            REVIEWER_ID,
            note=f"Coding remediation: {reason}",
        )
    if already_logged is None:
        payload = {
            "reason_code": "CODING_MISSING_STATEMENT"
            if not (question.get("problem_statement") or "").strip()
            else "CODING_CONTRACT_UNVERIFIED",
            "reason": reason,
            "question_title": question.get("title"),
            "existing_problem_statement": question.get("problem_statement"),
            "existing_constraints": question.get("constraints_text"),
            "existing_pseudocode": question.get("solution_pseudocode"),
            "missing_or_unverified": [
                "I/O contract",
                "verified reference solution",
                "public examples",
                "public and hidden judge tests",
            ],
            "source_evidence": {
                "source_id": question.get("source_id"),
                "source_question_number": question.get("source_question_number"),
            },
            "attempted": (
                "Inspected the before-apply statement, constraints, pseudocode, and "
                "source provenance. No content repair is claimed."
            ),
            "source_evidence": _source_evidence(question),
        }
        connection.execute(
            text("""
                INSERT INTO question_reviews (
                    question_id, reviewer_id, decision, notes
                )
                VALUES (:question_id, :reviewer_id, 'PENDING', :notes)
            """),
            {
                "question_id": question_id,
                "reviewer_id": REVIEWER_ID,
                "notes": marker + json.dumps(payload, ensure_ascii=False),
            },
        )
    return {
        "question_id": question_id,
        "source_question_number": question.get("source_question_number"),
        "title": question.get("title"),
        "source_evidence": _source_evidence(question),
        "problem_statement": question.get("problem_statement"),
        "solution_pseudocode": question.get("solution_pseudocode"),
        "old_status": question.get("status"),
        "final_status": "REVIEW",
        "fields_changed": [],
        "input_format": question.get("input_format"),
        "output_format": question.get("output_format"),
        "constraints": question.get("constraints_text"),
        "starter_code": question.get("starter_code"),
        "examples_count": int(question.get("example_count") or 0),
        "public_test_count": int(question.get("public_test_case_count") or 0),
        "hidden_test_count": int(question.get("hidden_test_case_count") or 0),
        "reference_solution_status": "NOT_VALIDATED",
        "starter_compile_status": "NOT_VALIDATED",
        "judge_status": "BLOCKED",
        "expected_output_verification": "NOT_RUN",
        "governance_status": "BLOCKED",
        "publication_status": "NOT_PUBLISHED",
        "review_reason": reason,
        "errors": [reason],
        "warnings": [],
        "database_commit_status": "COMMITTED_AS_REVIEW",
        "commit_timestamp": datetime.now().astimezone().isoformat(),
    }


def _unresolved_reason(question: dict) -> str:
    title = (question.get("title") or "").strip()
    statement = (question.get("problem_statement") or "").strip()
    if not statement:
        return (
            f"CODING_MISSING_STATEMENT: {title!r} has no problem statement. "
            "The supplied pseudocode alone does not establish the original task "
            "contract, so no statement, input/output format, or expected answer was invented."
        )
    return (
        f"{title!r} remains unrepaired in this pass. The source record has no "
        "input/output format, starter, examples, or judge cases, and no individually "
        "verified I/O contract and reference fixtures have been prepared for this item. "
        "No content or expected outputs were fabricated; per-question reconstruction "
        "and human review remain required."
    )


def _repair_one(question: dict, spec: dict, reviewer_id: int) -> dict:
    question_id = int(question["question_id"])
    old_status = question["status"]
    tests = [
        {
            "input_data": input_data,
            "expected_output": expected,
            "is_hidden": hidden,
            "points": 1,
        }
        for input_data, expected, hidden in spec["cases"]
    ]
    with engine.begin() as transaction:
        live = transaction.execute(
            text("""
                SELECT q.question_type, q.status, q.source_id, q.source_question_number,
                       q.title, c.problem_statement, c.constraints_text, c.input_format,
                       c.output_format, c.starter_code, c.solution_pseudocode,
                       c.solution_explanation, c.time_complexity, c.space_complexity
                FROM questions q
                JOIN coding_questions c ON c.question_id = q.question_id
                WHERE q.question_id = :question_id
                FOR UPDATE
            """),
            {"question_id": question_id},
        ).mappings().one_or_none()
        if live is None or live["question_type"] != "CODING":
            raise RuntimeError(f"Live coding question {question_id} changed.")
        if live["status"] != old_status:
            raise RuntimeError(f"Question {question_id} status changed since snapshot.")
        for field in (
            "source_id",
            "source_question_number",
            "title",
            "problem_statement",
            "constraints_text",
            "input_format",
            "output_format",
            "starter_code",
            "solution_pseudocode",
            "solution_explanation",
            "time_complexity",
            "space_complexity",
        ):
            if live[field] != question.get(field):
                raise RuntimeError(
                    f"Question {question_id} field {field} changed since snapshot."
                )
        existing_examples = transaction.execute(
            text("""
                SELECT example_number, input_data, output_data
                FROM question_examples WHERE question_id = :question_id
            """),
            {"question_id": question_id},
        ).mappings().all()
        existing_tests = transaction.execute(
            text("""
                SELECT test_case_number, input_data, expected_output, is_hidden
                FROM coding_test_cases WHERE question_id = :question_id
            """),
            {"question_id": question_id},
        ).mappings().all()
        if existing_examples or existing_tests:
            raise RuntimeError(
                f"Question {question_id} acquired manually reviewed examples/tests; "
                "refusing to overwrite."
            )

        transaction.execute(
            text("""
                UPDATE coding_questions
                SET input_format = :input_format,
                    output_format = :output_format,
                    starter_code = :starter_code,
                    solution_explanation = :solution_explanation,
                    time_complexity = COALESCE(time_complexity, :time_complexity),
                    space_complexity = COALESCE(space_complexity, :space_complexity)
                WHERE question_id = :question_id
            """),
            {
                "question_id": question_id,
                "input_format": spec["input_format"],
                "output_format": spec["output_format"],
                "starter_code": spec["starter"],
                "solution_explanation": spec["explanation"],
                "time_complexity": spec["time"],
                "space_complexity": spec["space"],
            },
        )
        for example_number, (input_data, output_data, _) in enumerate(spec["cases"][:2], 1):
            transaction.execute(
                text("""
                    INSERT INTO question_examples (
                        question_id, example_number, input_data, output_data, explanation
                    )
                    VALUES (
                        :question_id, :example_number, :input_data, :output_data, :explanation
                    )
                """),
                {
                    "question_id": question_id,
                    "example_number": example_number,
                    "input_data": input_data,
                    "output_data": output_data,
                    "explanation": spec["explanation"],
                },
            )
        for test_number, test in enumerate(tests, 1):
            transaction.execute(
                text("""
                    INSERT INTO coding_test_cases (
                        question_id, test_case_number, input_data, expected_output,
                        is_hidden, points
                    )
                    VALUES (
                        :question_id, :test_case_number, :input_data, :expected_output,
                        :is_hidden, :points
                    )
                """),
                {
                    "question_id": question_id,
                    "test_case_number": test_number,
                    **test,
                },
            )

        governance_errors = _governance_check(transaction, question_id)
        if governance_errors:
            raise RuntimeError(
                f"Governance rejected question {question_id}: {governance_errors}"
            )
        question_governance_service.transition_question_status(
            transaction,
            question_id,
            "REVIEW",
            reviewer_id,
            note="Individual coding contract, examples, and reference tests verified in Docker.",
        )
        fields_changed = [
            "input_format",
            "output_format",
            "starter_code",
            "solution_explanation",
            "question_examples",
            "coding_test_cases",
        ]
        if live["time_complexity"] is None:
            fields_changed.append("time_complexity")
        if live["space_complexity"] is None:
            fields_changed.append("space_complexity")
        review_note = {
            "reason_code": "CODING_INDIVIDUALLY_VALIDATED",
            "reason": "Reconstructed contract from the existing statement and constraints.",
            "fields_changed": fields_changed,
            "evidence": {
                "statement": live["problem_statement"],
                "constraints": live["constraints_text"],
                "existing_pseudocode": live["solution_pseudocode"],
                "reference_docker_status": "PASSED",
                "reference_test_count": len(tests),
                "starter_docker_status": "PASSED",
                "governance_errors": [],
            },
        }
        transaction.execute(
            text("""
                INSERT INTO question_reviews (
                    question_id, reviewer_id, decision, notes
                )
                VALUES (
                    :question_id, :reviewer_id, 'PENDING', :notes
                )
            """),
            {
                "question_id": question_id,
                "reviewer_id": reviewer_id,
                "notes": REVIEW_MARKER
                + str(question_id)
                + json.dumps(review_note, ensure_ascii=False),
            },
        )
        persisted = transaction.execute(
            text("""
                SELECT q.status, c.input_format, c.output_format, c.starter_code,
                       (SELECT COUNT(*) FROM question_examples e
                        WHERE e.question_id = q.question_id) AS examples_count,
                       (SELECT COUNT(*) FROM coding_test_cases tc
                        WHERE tc.question_id = q.question_id) AS tests_count
                FROM questions q
                JOIN coding_questions c ON c.question_id = q.question_id
                WHERE q.question_id = :question_id
            """),
            {"question_id": question_id},
        ).mappings().one()
        if (
            persisted["status"] != "REVIEW"
            or not persisted["input_format"]
            or not persisted["output_format"]
            or not persisted["starter_code"]
            or persisted["examples_count"] < 2
            or persisted["tests_count"] != len(tests)
        ):
            raise RuntimeError(f"Question {question_id} failed in-transaction persistence checks.")
        commit_status = "COMMITTED"

    with engine.connect() as verification:
        persisted = verification.execute(
            text("""
                SELECT q.status, c.input_format, c.output_format,
                       (SELECT COUNT(*) FROM question_examples e
                        WHERE e.question_id = q.question_id) AS examples_count,
                       (SELECT COUNT(*) FROM coding_test_cases tc
                        WHERE tc.question_id = q.question_id) AS tests_count,
                       (SELECT COUNT(*) FROM coding_test_cases tc
                        WHERE tc.question_id = q.question_id AND tc.is_hidden = TRUE) AS hidden_count,
                       (SELECT COUNT(*) FROM coding_test_cases tc
                        WHERE tc.question_id = q.question_id AND tc.is_hidden = FALSE) AS public_count
                FROM questions q
                JOIN coding_questions c ON c.question_id = q.question_id
                WHERE q.question_id = :question_id
            """),
            {"question_id": question_id},
        ).mappings().one()
        if persisted["status"] != "REVIEW" or int(persisted["tests_count"]) != len(tests):
            raise RuntimeError(f"Question {question_id} did not persist after commit.")

    return {
        "question_id": question_id,
        "source_question_number": question.get("source_question_number"),
        "title": question.get("title"),
        "source_evidence": _source_evidence(question),
        "problem_statement": question.get("problem_statement"),
        "solution_pseudocode": question.get("solution_pseudocode"),
        "old_status": old_status,
        "final_status": persisted["status"],
        "fields_changed": review_note["fields_changed"],
        "input_format": spec["input_format"],
        "output_format": spec["output_format"],
        "constraints": question.get("constraints_text"),
        "starter_code": spec["starter"],
        "examples_count": int(persisted["examples_count"]),
        "public_test_count": int(persisted["public_count"]),
        "hidden_test_count": int(persisted["hidden_count"]),
        "reference_solution_status": "PASSED",
        "starter_compile_status": "PASSED",
        "judge_status": "PASSED",
        "expected_output_verification": "VERIFIED",
        "governance_status": "PASSED",
        "publication_status": "NOT_PUBLISHED_PENDING_REVIEW",
        "review_reason": "Docker and governance passed; human review/approval remains pending.",
        "errors": [],
        "warnings": [],
        "database_commit_status": commit_status,
        "commit_timestamp": datetime.now().astimezone().isoformat(),
    }


def _write_reports(records: list[dict], counts: dict, integrity: dict) -> None:
    REPORTS.mkdir(exist_ok=True)
    payload = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "question_total": EXPECTED_COUNT,
        "counts": counts,
        "database_integrity": integrity,
        "records": records,
    }
    RESULT_JSON.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=_json_default) + "\n",
        encoding="utf-8",
    )
    fields = (
        "question_id",
        "source_question_number",
        "title",
        "problem_statement",
        "solution_pseudocode",
        "source_evidence",
        "old_status",
        "final_status",
        "fields_changed",
        "input_format",
        "output_format",
        "constraints",
        "starter_code",
        "examples_count",
        "public_test_count",
        "hidden_test_count",
        "reference_solution_status",
        "starter_compile_status",
        "judge_status",
        "expected_output_verification",
        "governance_status",
        "publication_status",
        "review_reason",
        "errors",
        "warnings",
        "database_commit_status",
        "commit_timestamp",
    )
    with RESULT_CSV.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for row in records:
            writer.writerow(
                {
                    field: (
                        json.dumps(row.get(field), ensure_ascii=False)
                        if field in {
                            "fields_changed",
                            "errors",
                            "warnings",
                            "source_evidence",
                            "solution_pseudocode",
                        }
                        else row.get(field)
                    )
                    for field in fields
                }
            )
    summary = [
        "# Coding Question Remediation (290)",
        "",
        f"Generated: {payload['generated_at']}",
        "",
        f"- Total coding questions: {counts['total']}",
        f"- Content repaired and sent for review: {counts['content_repaired']}",
        f"- Left in REVIEW: {counts['review']}",
        f"- Rolled back: {counts['rolled_back']}",
        f"- Docker preflight blocked: {counts['preflight_blocked']}",
        f"- Examples inserted: {counts['examples_inserted']}",
        f"- Test cases inserted: {counts['test_cases_inserted']}",
        f"- Judge-validated questions: {counts['judge_validated']}",
        f"- Only approved remediation tables changed: {integrity['only_allowed_tables_changed']}",
        "",
        "Only individually validated repairs with passing reference/starter Docker checks and zero governance errors were committed as content. All questions remain REVIEW; no approval or publication was fabricated.",
        "",
        "## Per-question outcome",
        "",
        "| ID | Status | Commit | Judge | Reason |",
        "|---:|---|---|---|---|",
    ]
    for row in records:
        reason = row.get("review_reason") or "Verified content and governance"
        summary.append(
            f"| {row['question_id']} | {row['final_status']} | "
            f"{row['database_commit_status']} | {row['judge_status']} | "
            f"{reason.replace('|', '\\|')} |"
        )
    RESULT_MD.write_text("\n".join(summary) + "\n", encoding="utf-8")


def main() -> None:
    if not BEFORE_JSON.exists():
        raise SystemExit(
            "Required before-apply snapshot is missing; refusing production writes."
        )
    if not docker_is_ready():
        raise SystemExit(
            "Configured Docker judge daemon/image unavailable; refusing production writes."
        )
    snapshot = json.loads(BEFORE_JSON.read_text(encoding="utf-8"))
    snapshot_by_id = {int(row["question_id"]): row for row in snapshot["records"]}
    if len(snapshot_by_id) != EXPECTED_COUNT:
        raise SystemExit("Before-apply snapshot must contain exactly 290 unique questions.")
    with engine.connect() as connection:
        database = connection.execute(text("SELECT DATABASE()")).scalar_one()
        live_rows = connection.execute(
            text("""
                SELECT q.question_id, q.question_type, q.status, q.source_id,
                       q.source_question_number, q.title, c.problem_statement,
                       c.constraints_text, c.input_format, c.output_format,
                       c.starter_code, c.solution_pseudocode,
                       c.solution_explanation, c.time_complexity, c.space_complexity
                FROM questions q
                JOIN coding_questions c ON c.question_id = q.question_id
                WHERE q.question_type = 'CODING'
                ORDER BY q.question_id
            """)
        ).mappings().all()
        question_state_before = {
            int(row["question_id"]): dict(row)
            for row in connection.execute(
                text("""
                    SELECT question_id, question_type, status, difficulty,
                           source_id, track_id, title, content_hash
                    FROM questions
                """)
            ).mappings()
        }
        reviewers = connection.execute(
            text("""
                SELECT user_id FROM users
                WHERE user_id = :reviewer_id AND role = 'ADMIN' AND is_active = TRUE
            """),
            {"reviewer_id": REVIEWER_ID},
        ).scalar_one_or_none()
        table_names = (
            "questions",
            "mcq_questions",
            "mcq_options",
            "coding_questions",
            "question_examples",
            "coding_test_cases",
            "question_reviews",
            "question_status_history",
            "sources",
            "tracks",
            "topics",
            "subtopics",
            "question_subtopics",
            "question_tags",
            "tags",
            "mock_tests",
            "mock_test_questions",
            "attempts",
            "attempt_answers",
            "coding_submissions",
        )
        before_counts = {
            table: int(connection.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one())
            for table in table_names
        }
    if (
        database != snapshot["database"]
        or len(live_rows) != EXPECTED_COUNT
        or len(question_state_before) != 2207
        or reviewers is None
        or {int(row["question_id"]) for row in live_rows} != set(snapshot_by_id)
    ):
        raise SystemExit("Database, coding count, or active reviewer safety check failed.")
    for table, snapshot_key in (
        ("questions", "questions"),
        ("coding_questions", "coding_questions"),
        ("question_examples", "question_examples"),
        ("coding_test_cases", "coding_test_cases"),
        ("question_reviews", "question_reviews"),
        ("question_status_history", "question_status_history"),
        ("mock_tests", "mock_tests"),
        ("mock_test_questions", "mock_test_questions"),
        ("attempts", "attempts"),
        ("attempt_answers", "attempt_answers"),
        ("coding_submissions", "coding_submissions"),
    ):
        if before_counts[table] != int(snapshot["counts"][snapshot_key]):
            raise SystemExit(
                f"Live {table} count differs from the before-apply snapshot; refusing writes."
            )
    for live in live_rows:
        question_id = int(live["question_id"])
        original = snapshot_by_id[question_id]
        for field in (
            "status",
            "source_id",
            "source_question_number",
            "title",
            "problem_statement",
            "constraints_text",
            "input_format",
            "output_format",
            "starter_code",
            "solution_pseudocode",
            "solution_explanation",
            "time_complexity",
            "space_complexity",
        ):
            if live[field] != original.get(field):
                raise SystemExit(
                    f"Question {question_id} field {field} differs from the "
                    "before-apply snapshot; refusing writes."
                )
        if live["status"] != "DRAFT":
            raise SystemExit(
                f"Question {question_id} is no longer DRAFT; refusing rerun."
            )
    if not set(SPECS).issubset(snapshot_by_id):
        raise SystemExit("A repair specification references a question outside the snapshot.")

    preflight = {}
    for question_id, spec in SPECS.items():
        print(f"DOCKER PREFLIGHT {question_id}: {len(spec['cases'])} tests", flush=True)
        cases = [
            {
                "input_data": input_data,
                "expected_output": expected,
                "is_hidden": hidden,
                "points": 1,
            }
            for input_data, expected, hidden in spec["cases"]
        ]
        try:
            reference = _reference_result(question_id, spec["reference"], cases)
            starter = execute_submission(
                80_000_000 + question_id,
                spec["starter"],
                [{"input_data": "", "expected_output": ""}],
            )
            if starter.get("status") != "PASSED":
                raise RuntimeError(
                    "Starter compile/execute failed: "
                    f"{starter.get('safe_error_message') or starter.get('status')}"
                )
            preflight[question_id] = None
            print(
                f"DOCKER PREFLIGHT {question_id}: PASSED "
                f"({reference['tests_passed']}/{len(cases)} tests; starter PASSED)",
                flush=True,
            )
        except Exception as error:
            preflight[question_id] = f"{type(error).__name__}: {error}"
            print(
                f"DOCKER PREFLIGHT {question_id}: BLOCKED ({preflight[question_id]})",
                flush=True,
            )

    results = []
    rolled_back = 0
    preflight_blocked = 0
    total = 0
    for batch_start in range(0, EXPECTED_COUNT, BATCH_SIZE):
        batch_ids = sorted(snapshot_by_id)[batch_start : batch_start + BATCH_SIZE]
        for question_id in batch_ids:
            total += 1
            question = snapshot_by_id[question_id]
            print(f"QUESTION {total}/{EXPECTED_COUNT}", flush=True)
            print(f"ID: {question_id}", flush=True)
            print(f"Title: {question.get('title')}", flush=True)
            spec = SPECS.get(question_id)
            if spec is not None:
                if preflight[question_id] is not None:
                    preflight_blocked += 1
                    reason = (
                        "The question-specific starter/reference solution did not pass "
                        f"Docker preflight: {preflight[question_id]}. No content repair was applied."
                    )
                    with engine.begin() as connection:
                        result = _record_for_review(connection, question, reason)
                    result["database_commit_status"] = "CONTENT_NOT_APPLIED_REVIEW_COMMITTED"
                    result["errors"] = [reason]
                    print("Judge/governance: BLOCKED; no content applied", flush=True)
                    print("DATABASE: REVIEW COMMITTED", flush=True)
                else:
                    try:
                        result = _repair_one(question, spec, REVIEWER_ID)
                        print("Judge: PASSED; governance: PASSED", flush=True)
                        print("DATABASE: COMMITTED; final status: REVIEW", flush=True)
                    except Exception as error:
                        rolled_back += 1
                        reason = (
                            "Individually specified repair failed a transactional "
                            "governance/persistence check; question content transaction "
                            f"rolled back ({type(error).__name__}: {error})."
                        )
                        with engine.begin() as connection:
                            result = _record_for_review(connection, question, reason)
                        result["database_commit_status"] = (
                            "CONTENT_ROLLED_BACK_REVIEW_COMMITTED"
                        )
                        result["errors"] = [reason]
                        print(
                            f"Judge/governance: BLOCKED ({type(error).__name__})",
                            flush=True,
                        )
                        print("DATABASE: REVIEW COMMITTED", flush=True)
            else:
                reason = _unresolved_reason(question)
                with engine.begin() as connection:
                    result = _record_for_review(connection, question, reason)
                print("Judge: NOT RUN; governance: BLOCKED", flush=True)
                print("DATABASE: COMMITTED AS REVIEW", flush=True)
            results.append(result)
        with engine.connect() as connection:
            persisted = int(
                connection.execute(
                    text("""
                        SELECT COUNT(*) FROM questions
                        WHERE question_type='CODING'
                          AND status IN ('REVIEW', 'PUBLISHED')
                    """)
                ).scalar_one()
            )
        print(
            f"BATCH VERIFIED: committed/persisted non-DRAFT coding questions={persisted}",
            flush=True,
        )

    with engine.connect() as connection:
        final_counts = {
            row["status"]: int(row["n"])
            for row in connection.execute(
                text("""
                    SELECT status, COUNT(*) AS n
                    FROM questions WHERE question_type='CODING' GROUP BY status
                """)
            ).mappings()
        }
        final_counts.setdefault("DRAFT", 0)
        final_counts.setdefault("REVIEW", 0)
        final_counts.setdefault("PUBLISHED", 0)
        final_counts["total"] = int(
            connection.execute(
                text("SELECT COUNT(*) FROM questions WHERE question_type='CODING'")
            ).scalar_one()
        )
        published_rows = connection.execute(
            text("""
                SELECT question_id FROM questions
                WHERE question_type='CODING' AND status='PUBLISHED'
            """)
        ).scalars().all()
        final_counts["published_governance_errors"] = sum(
            bool(question_governance_service.validate_question_for_publication(connection, int(qid)))
            for qid in published_rows
        )
        final_counts["examples_inserted"] = sum(
            int(record.get("examples_count") or 0) for record in results
            if record["database_commit_status"] == "COMMITTED"
        )
        final_counts["test_cases_inserted"] = sum(
            int(record.get("public_test_count") or 0) + int(record.get("hidden_test_count") or 0)
            for record in results
            if record["database_commit_status"] == "COMMITTED"
        )
        final_counts["judge_validated"] = sum(
            record["judge_status"] == "PASSED" for record in results
        )
        final_counts["content_repaired"] = sum(
            record["database_commit_status"] == "COMMITTED" for record in results
        )
        final_counts["rolled_back"] = rolled_back
        final_counts["preflight_blocked"] = preflight_blocked
        final_counts["review"] = final_counts["REVIEW"]
        after_counts = {
            table: int(connection.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one())
            for table in table_names
        }
        question_state_after = {
            int(row["question_id"]): dict(row)
            for row in connection.execute(
                text("""
                    SELECT question_id, question_type, status, difficulty,
                           source_id, track_id, title, content_hash
                    FROM questions
                """)
            ).mappings()
        }
        coding_rows_after = connection.execute(
            text("""
                SELECT q.question_id, q.status, q.source_id, q.source_question_number,
                       q.title, c.problem_statement, c.constraints_text, c.input_format,
                       c.output_format, c.starter_code, c.solution_pseudocode,
                       c.solution_explanation, c.time_complexity, c.space_complexity
                FROM questions q
                JOIN coding_questions c ON c.question_id = q.question_id
                WHERE q.question_type = 'CODING'
            """)
        ).mappings().all()
    if final_counts["total"] != EXPECTED_COUNT or total != EXPECTED_COUNT:
        raise RuntimeError(f"Final coding count safety check failed: {final_counts}.")
    if final_counts["published_governance_errors"] != 0:
        raise RuntimeError(f"Published coding questions failed governance: {final_counts}.")
    if final_counts["PUBLISHED"] != 0 or final_counts["DRAFT"] != 0:
        raise RuntimeError(f"Coding questions have an unexpected final status: {final_counts}.")
    if set(question_state_before) != set(question_state_after):
        raise RuntimeError("Question IDs changed during coding remediation.")
    for question_id, before in question_state_before.items():
        after = question_state_after[question_id]
        for field in (
            "question_type",
            "difficulty",
            "source_id",
            "track_id",
            "title",
            "content_hash",
        ):
            if before[field] != after[field]:
                raise RuntimeError(
                    f"Question {question_id} field {field} changed unexpectedly."
                )
        expected_status = "REVIEW" if before["question_type"] == "CODING" else before["status"]
        if after["status"] != expected_status:
            raise RuntimeError(f"Question {question_id} has unexpected final status.")

    committed_ids = {
        int(record["question_id"])
        for record in results
        if record["database_commit_status"] == "COMMITTED"
    }
    allowed_coding_fields = {
        "input_format",
        "output_format",
        "starter_code",
        "solution_explanation",
        "time_complexity",
        "space_complexity",
    }
    coding_before = {int(row["question_id"]): row for row in live_rows}
    for after in coding_rows_after:
        question_id = int(after["question_id"])
        before = coding_before[question_id]
        for field in (
            "source_id",
            "source_question_number",
            "title",
            "problem_statement",
            "constraints_text",
            "solution_pseudocode",
        ):
            if after[field] != before[field]:
                raise RuntimeError(
                    f"Coding question {question_id} field {field} changed unexpectedly."
                )
        if question_id not in committed_ids:
            for field in allowed_coding_fields:
                if after[field] != before[field]:
                    raise RuntimeError(
                        f"Unrepaired question {question_id} field {field} changed."
                    )
    expected_deltas = {table: 0 for table in table_names}
    expected_deltas.update({
        "question_examples": final_counts["examples_inserted"],
        "coding_test_cases": final_counts["test_cases_inserted"],
        "question_reviews": EXPECTED_COUNT,
        "question_status_history": EXPECTED_COUNT,
    })
    actual_deltas = {
        table: after_counts[table] - before_counts[table]
        for table in table_names
    }
    if actual_deltas != expected_deltas:
        raise RuntimeError(
            f"Unexpected table-count changes detected: "
            f"expected {expected_deltas}, observed {actual_deltas}."
        )
    integrity = {
        "database": database,
        "before_counts": before_counts,
        "after_counts": after_counts,
        "expected_count_deltas": expected_deltas,
        "actual_count_deltas": actual_deltas,
        "only_allowed_tables_changed": all(
            delta == 0
            for table, delta in actual_deltas.items()
            if table not in {
                "questions",
                "coding_questions",
                "question_examples",
                "coding_test_cases",
                "question_reviews",
                "question_status_history",
            }
        ),
        "questions_row_count_changed": actual_deltas["questions"] != 0,
        "question_fields_updated": ["status", "automatic updated_at timestamp"],
        "content_table_fields_updated": [
            "coding_questions",
            "question_examples",
            "coding_test_cases",
        ],
        "question_difficulty_unchanged": True,
        "question_source_taxonomy_and_content_hash_unchanged": True,
        "unrepaired_coding_content_unchanged": True,
    }
    _write_reports(results, final_counts, integrity)
    print("\n290 CODING QUESTION REMEDIATION")
    for key, value in final_counts.items():
        print(f"{key}: {value}")
    print(f"result_json: {RESULT_JSON}")
    print(f"result_csv: {RESULT_CSV}")
    print(f"result_markdown: {RESULT_MD}")


if __name__ == "__main__":
    main()
