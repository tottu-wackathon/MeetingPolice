#!/usr/bin/env python3
"""
Test script for conjunction/filler word detection
"""

import sys
import os
sys.path.append('.')

from backend.session.analysis_handler import AnalysisHandler

def test_conjunction_detection():
    """Test the conjunction/filler detection functionality"""
    handler = AnalysisHandler()
    
    test_cases = [
        ('のが、やっぱりちょっと', True),  # User's example - should be detected
        ('やっぱりちょっと', True),
        ('それでですね', True),
        ('でも、まあ', True),
        ('そうですね、なるほど', True),
        ('プロジェクトの進捗について', False),  # Should not be detected
        ('ミーティングの議題は', False),  # Should not be detected
        ('あー、そうですね', True),
        ('えーっと、ちょっと', True),
        ('のが', True),
        ('やっぱり', True),
        ('重要な議題について話し合いましょう', False),  # Should not be detected
    ]
    
    print('Testing conjunction/filler detection:')
    print('=' * 50)
    
    all_passed = True
    for text, expected in test_cases:
        try:
            result = handler._is_conjunction_or_filler(text)
            status = "✅ PASS" if result == expected else "❌ FAIL"
            print(f'{status} "{text}" -> {result} (expected: {expected})')
            if result != expected:
                all_passed = False
        except Exception as e:
            print(f'❌ ERROR "{text}" -> Exception: {e}')
            all_passed = False
    
    print('=' * 50)
    if all_passed:
        print('✅ All tests passed!')
    else:
        print('❌ Some tests failed!')
    
    return all_passed

if __name__ == '__main__':
    test_conjunction_detection()