INSERT INTO submissions (image_url, extracted_data, status)
VALUES (
    'https://example.com/sample-invoice.jpg',
    '{"invoice_number": "2864", "invoice_date": "2021-08-06", "total": "53.90"}',
    'pending_review'
);