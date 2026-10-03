# SWIFT Message Field Patterns

This document provides an overview of the field patterns used in the SWIFT parser for various message types.

## Field Pattern Format

SWIFT field formats use a specific syntax to define the expected structure of each field:

- `n`: Digits only (0-9)
- `a`: Uppercase letters only (A-Z)
- `c`: Uppercase alphanumeric characters only (A-Z, 0-9)
- `x`: Any character from the SWIFT character set
- `d`: Decimal number (includes decimal point and comma)
- `!`: Fixed length
- `[...]`: Optional component
- `*`: Repetition (e.g., 5*35x means 5 lines of 35 characters)
- `$`: Line break

## Common Field Patterns

Below are some of the most commonly used field patterns in various SWIFT message types:

### MT103 (Single Customer Credit Transfer)

| Field | Format | Description |
|-------|--------|-------------|
| 20 | 16x | Sender's Reference |
| 23B | 4!c | Bank Operation Code |
| 32A | 6!n3!a15d | Value Date, Currency, Amount |
| 50K | [/34x]$4*35x | Ordering Customer |
| 59 | [/34x]$4*35x | Beneficiary Customer |
| 71A | 3!a | Details of Charges |

### MT202 (General Financial Institution Transfer)

| Field | Format | Description |
|-------|--------|-------------|
| 20 | 16x | Transaction Reference Number |
| 21 | 16x | Related Reference |
| 32A | 6!n3!a15d | Value Date, Currency, Amount |
| 52A | [/1!a][/34x]$4*35x | Ordering Institution |
| 58A | [/1!a][/34x]$4*35x | Beneficiary Institution |

### MT940/MT950 (Customer/Bank Statement)

| Field | Format | Description |
|-------|--------|-------------|
| 20 | 16x | Transaction Reference Number |
| 25 | 35x | Account Identification |
| 28C | 5n[/5n] | Statement Number/Sequence Number |
| 60F | 1!a6!n3!a15d | Opening Balance |
| 61 | 6!n[4!n]2a[1!a]15d[1!a4!c][//16x][34x] | Statement Line |
| 62F | 1!a6!n3!a15d | Closing Balance |

## Using Field Patterns

The parser uses the patterns defined in `patterns.json` to:

1. **Validate** that field content matches expected format
2. **Parse** field content into structured data
3. **Format** field content for display or output

### Example Pattern Usage

For a field with pattern `6!n3!a15d` (like field 32A):
- `6!n`: Exactly 6 digits (e.g., YYMMDD date format)
- `3!a`: Exactly 3 uppercase letters (currency code)
- `15d`: Up to 15 characters representing a decimal number

Example value: `210623EUR100000,00`

## Extended Pattern Support

The parser has been expanded to support all common SWIFT message types including:

- MT101: Request for Transfer
- MT103: Single Customer Credit Transfer
- MT202: General Financial Institution Transfer
- MT202COV: Cover Payment
- MT205: Financial Institution Transfer Execution
- MT900: Confirmation of Debit
- MT910: Confirmation of Credit
- MT940: Customer Statement
- MT942: Interim Statement
- MT950: Statement Message

## Implementation Notes

When adding new field patterns, ensure:

1. The pattern accurately reflects the SWIFT standard specification
2. The pattern is added to the `patterns.json` file with the correct field tag
3. Include descriptive field names to improve readability
4. Test parsing with sample messages to verify correct functionality

## References

- [SWIFT Standards](https://www.swift.com/standards)
- [SWIFT Message Structure](https://www.paiementor.com/swift-message-structure/)
- [SWIFT Character Set](https://www.ibm.com/docs/en/ssfksj_7.5.0/com.ibm.mq.ref.dev.doc/q111210_.html) 