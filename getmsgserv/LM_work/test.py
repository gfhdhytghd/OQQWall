import sys

def main():
    if len(sys.argv) != 3:
        print("Usage: python3 test.py <input> <output>")
        sys.exit(1)

    input_value = sys.argv[1]
    output_value = sys.argv[2]

    print(f"Input: {input_value}")
    print(f"Output: {output_value}")

if __name__ == "__main__":
    main()

