#!/usr/bin/env python3
"""
Test script for WebAgent

This script tests the WebAgent functionality with mock data to verify:
1. Agent initialization
2. Data fetching and transformation
3. Statistics reporting
4. Error handling

Usage:
    python test_web_agent.py

The test uses mock data (no API keys required) to verify the complete workflow.
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from loguru import logger
from src.agents.web_agent import WebAgent

# Configure logging for test
logger.add(
    "logs/test_web_agent.log",
    rotation="10 MB",
    retention="7 days",
    level="DEBUG"
)


def test_agent_initialization():
    """Test 1: Agent initialization"""
    print("\n" + "="*80)
    print("TEST 1: Agent Initialization")
    print("="*80)

    try:
        agent = WebAgent()
        print(f"✓ Agent initialized: {agent.agent_name}")
        print(f"  - Max URLs: {agent.max_urls}")
        print(f"  - Mock mode: {agent.use_mock}")
        print(f"  - Timeout: {agent.timeout}s")
        return True
    except Exception as e:
        print(f"✗ Initialization failed: {e}")
        return False


def test_mock_data_fetch():
    """Test 2: Fetch data with mock mode"""
    print("\n" + "="*80)
    print("TEST 2: Mock Data Fetching")
    print("="*80)

    try:
        agent = WebAgent()
        agent.use_mock = True  # Force mock mode for testing

        # Fetch data for floods
        records = agent.fetch_data(
            start_date="2025-11-01",
            end_date="2025-11-09",
            disaster_type="floods"
        )

        print(f"✓ Data fetched successfully")
        print(f"  - Records returned: {len(records)}")

        if records:
            print(f"\nSample record:")
            sample = records[0]
            print(f"  - Event ID: {sample.get('source_event_id')}")
            print(f"  - Event time: {sample.get('event_time')}")
            print(f"  - Location: {sample.get('location_text')}")
            print(f"  - Disaster type: {sample.get('disaster_type')}")
            print(f"  - Fatalities: {sample.get('fatalities')}")
            print(f"  - Affected: {sample.get('affected')}")

        return len(records) > 0

    except Exception as e:
        print(f"✗ Data fetch failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_statistics_tracking():
    """Test 3: Statistics tracking"""
    print("\n" + "="*80)
    print("TEST 3: Statistics Tracking")
    print("="*80)

    try:
        agent = WebAgent()
        agent.use_mock = True

        # Fetch data
        agent.fetch_data(disaster_type="earthquakes")

        # Get statistics
        stats = agent.get_statistics()

        print(f"✓ Statistics tracked:")
        print(f"  - URLs searched: {stats['urls_searched']}")
        print(f"  - URLs crawled: {stats['urls_crawled']}")
        print(f"  - Events extracted: {stats['events_extracted']}")
        print(f"  - Records saved: {stats['records_saved']}")
        print(f"  - Errors: {stats['errors']}")

        return stats['events_extracted'] > 0

    except Exception as e:
        print(f"✗ Statistics test failed: {e}")
        return False


def test_packet_transformation():
    """Test 4: Packet transformation logic"""
    print("\n" + "="*80)
    print("TEST 4: Packet Transformation")
    print("="*80)

    try:
        agent = WebAgent()

        # Create sample packets
        sample_packets = [
            {
                "packet_id": "test_001",
                "packet_type": "discrete_disaster_event",
                "temporal": {
                    "start_date": "2025-11-06",
                    "end_date": None
                },
                "spatial": {
                    "primary_location": "Kerala",
                    "affected_locations": ["Kerala", "Kochi"]
                },
                "impact": {
                    "deaths": 25,
                    "injured": 50,
                    "displaced": 1000
                },
                "event": {
                    "event_type": "flood",
                    "description": "Test flood event"
                },
                "source": {
                    "url": "https://test.com",
                    "title": "Test Article"
                }
            },
            {
                "packet_id": "test_002",
                "packet_type": "discrete_disaster_event",
                "temporal": {
                    "start_date": "RELATIVE:today",
                    "end_date": None
                },
                "spatial": {
                    "primary_location": "Maharashtra",
                    "affected_locations": ["Maharashtra"]
                },
                "impact": {
                    "deaths": 0,
                    "injured": 10,
                    "displaced": 0
                },
                "event": {
                    "event_type": "earthquake",
                    "description": "Test earthquake"
                },
                "source": {
                    "url": "https://test2.com",
                    "title": "Test Article 2"
                }
            }
        ]

        # Transform packets
        records = agent._transform_packets_to_records(sample_packets)

        print(f"✓ Transformation completed:")
        print(f"  - Input packets: {len(sample_packets)}")
        print(f"  - Output records: {len(records)}")

        if records:
            print(f"\nTransformed record samples:")
            for idx, record in enumerate(records):
                print(f"\n  Record {idx + 1}:")
                print(f"    - Event ID: {record['source_event_id']}")
                print(f"    - Time: {record['event_time']}")
                print(f"    - Location: {record['location_text']}")
                print(f"    - Type: {record['disaster_type']}")
                print(f"    - Fatalities: {record['fatalities']}")
                print(f"    - Affected: {record['affected']}")

        return len(records) == len(sample_packets)

    except Exception as e:
        print(f"✗ Transformation test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_error_handling():
    """Test 5: Error handling"""
    print("\n" + "="*80)
    print("TEST 5: Error Handling")
    print("="*80)

    try:
        agent = WebAgent()

        # Test with invalid packets
        invalid_packets = [
            {"packet_type": "wrong_type"},  # Wrong type
            {"packet_type": "discrete_disaster_event"},  # Missing data
            None,  # Null packet
        ]

        records = agent._transform_packets_to_records(invalid_packets)

        print(f"✓ Error handling works:")
        print(f"  - Invalid packets: {len(invalid_packets)}")
        print(f"  - Valid records generated: {len(records)}")
        print(f"  - Errors encountered: {agent.stats['errors']}")

        return True

    except Exception as e:
        print(f"✗ Error handling test failed: {e}")
        return False


def main():
    """Run all tests"""
    print("\n" + "="*80)
    print("WEBAGENT TEST SUITE")
    print("="*80)
    print("Testing AI-Powered Web Data Acquisition Agent")
    print("This test uses MOCK DATA - no API keys required\n")

    tests = [
        ("Initialization", test_agent_initialization),
        ("Mock Data Fetch", test_mock_data_fetch),
        ("Statistics Tracking", test_statistics_tracking),
        ("Packet Transformation", test_packet_transformation),
        ("Error Handling", test_error_handling),
    ]

    results = []
    for test_name, test_func in tests:
        try:
            passed = test_func()
            results.append((test_name, passed))
        except Exception as e:
            print(f"\n✗ Test '{test_name}' crashed: {e}")
            results.append((test_name, False))

    # Print summary
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)

    passed_count = sum(1 for _, passed in results if passed)
    total_count = len(results)

    for test_name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{status}: {test_name}")

    print(f"\nResults: {passed_count}/{total_count} tests passed")

    if passed_count == total_count:
        print("\n🎉 All tests passed! WebAgent is ready to use.")
        return 0
    else:
        print(f"\n⚠️  {total_count - passed_count} test(s) failed. Please review errors above.")
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
