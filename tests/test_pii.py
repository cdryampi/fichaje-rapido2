
import pytest
import json
from unittest.mock import MagicMock, patch
import sys
import os

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import PII_SCHEMA, validate_and_repair_json

def test_valid_json():
    valid = '{"sensitive": [{"label":"Name","value":"John","confidence":"high"}], "non_sensitive": []}'
    result = validate_and_repair_json(valid, PII_SCHEMA)
    assert len(result["sensitive"]) == 1
    assert result["sensitive"][0]["value"] == "John"

def test_schema_violation_repair():
    # Missing required 'confidence'
    invalid = '{"sensitive": [{"label":"Name","value":"John"}], "non_sensitive": []}'
    
    # Mock LLM response for repair
    with patch("openai.Client") as MockClient:
        mock_instance = MockClient.return_value
        mock_instance.chat.completions.create.return_value.choices[0].message.content = \
            '{"sensitive": [{"label":"Name","value":"John","confidence":"high"}], "non_sensitive": []}'
        
        result = validate_and_repair_json(invalid, PII_SCHEMA, retry_count=1)
        assert result["sensitive"][0]["confidence"] == "high"

def test_malformed_json_repair():
    # Missing closing brace
    malformed = '{"sensitive": [], "non_sensitive": []'
    
    with patch("openai.Client") as MockClient:
        mock_instance = MockClient.return_value
        mock_instance.chat.completions.create.return_value.choices[0].message.content = \
            '{"sensitive": [], "non_sensitive": []}'
            
        result = validate_and_repair_json(malformed, PII_SCHEMA, retry_count=1)
        assert result["non_sensitive"] == []

def test_unrepairable_json():
    malformed = '{broken_json'
    
    with patch("openai.Client") as MockClient:
        # LLM fails to provide valid JSON too
        mock_instance = MockClient.return_value
        mock_instance.chat.completions.create.return_value.choices[0].message.content = 'Still broken'
        
        result = validate_and_repair_json(malformed, PII_SCHEMA, retry_count=1)
        assert "error" in result
