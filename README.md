# Content Moderation System

A Firebase Cloud Functions-based content moderation system for image and text content, using Google Cloud Vision SafeSearch for image moderation and keyword filtering for text moderation.

## Features

- **Image Moderation**: Automatic screening of uploaded images using Google Cloud Vision SafeSearch
- **Text Moderation**: Keyword and regex-based filtering for hate speech, harassment, and inappropriate content
- **Thumbnail Generation**: Automatic compression and thumbnail creation for approved images
- **Rate Limiting**: Per-user rate limits to prevent abuse
- **User Reporting**: Allow users to report inappropriate content
- **Logging**: Comprehensive logging of all moderation decisions

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Firebase Storage                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │   /pending   │  │  /approved   │  │    /thumbnails       │  │
│  └──────────────┘  └──────────────┘  └──────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
         │                   ▲                    ▲
         ▼                   │                    │
┌─────────────────────────────────────────────────────────────────┐
│                     Cloud Functions (Python)                     │
│  ┌──────────────────┐  ┌─────────────┐  ┌──────────────────┐   │
│  │ on_image_upload  │  │validate_text│  │  submit_report   │   │
│  └────────┬─────────┘  └─────────────┘  └──────────────────┘   │
│           │                                                      │
│           ▼                                                      │
│  ┌──────────────────┐                                           │
│  │ Cloud Vision API │                                           │
│  │   SafeSearch     │                                           │
│  └──────────────────┘                                           │
└─────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│                         Firestore                                │
│  ┌────────────────┐  ┌────────────────┐  ┌─────────────────┐   │
│  │moderation_logs │  │blocked_content │  │    reports      │   │
│  └────────────────┘  └────────────────┘  └─────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

## Project Structure

```
Image:Messages App/
├── functions/
│   ├── main.py              # Cloud Functions entry point
│   ├── image_moderation.py  # Vision API integration
│   ├── text_moderation.py   # Keyword filtering
│   ├── image_processing.py  # Thumbnail/compression
│   ├── rate_limiter.py      # Rate limiting
│   ├── reporting.py         # User reports
│   ├── utils.py             # Shared utilities
│   ├── blocklist.txt        # Blocked words/phrases
│   ├── requirements.txt     # Python dependencies
│   └── tests/               # Unit tests
├── docs/
│   ├── API_DOCUMENTATION.md # API reference for iOS team
│   └── SETUP_GUIDE.md       # Setup instructions
├── firebase.json            # Firebase configuration
├── firestore.rules          # Firestore security rules
├── storage.rules            # Storage security rules
└── README.md                # This file
```

## Quick Start

### Prerequisites

- Python 3.12+
- Node.js 18+ (for Firebase CLI)
- Firebase CLI (`npm install -g firebase-tools`)
- Google Cloud account with billing enabled

### Setup

1. **Clone and install dependencies**:
   ```bash
   cd functions
   python -m venv venv
   source venv/bin/activate  # On Windows: .\venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. **Configure Firebase**:
   ```bash
   firebase login
   firebase use --add  # Select your project
   ```

3. **Enable Cloud Vision API**:
   - Go to [Cloud Console](https://console.cloud.google.com/)
   - Enable "Cloud Vision API" for your project

4. **Deploy**:
   ```bash
   firebase deploy
   ```

## Cloud Functions

| Function | Trigger | Description |
|----------|---------|-------------|
| `on_image_upload` | Storage (pending/) | Moderates uploaded images |
| `validate_text` | HTTPS Callable | Validates text content |
| `submit_report` | HTTPS Callable | Handles user reports |
| `get_rate_limits` | HTTPS Callable | Returns user's rate limit status |
| `process_queued_images` | Scheduled (5 min) | Retries failed moderations |
| `cleanup_rate_limits_scheduled` | Scheduled (daily) | Cleans up old rate limit data |

## API Reference

See [API_DOCUMENTATION.md](docs/API_DOCUMENTATION.md) for detailed API documentation.

### Quick Example (iOS)

```swift
// Validate text before sending
Functions.functions().httpsCallable("validate_text").call(["text": message]) { result, error in
    guard let data = result?.data as? [String: Any],
          let allowed = data["allowed"] as? Bool,
          allowed else {
        // Handle blocked content
        return
    }
    // Send message
}
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `IMAGE_MODERATION_THRESHOLD` | `LIKELY` | Minimum level to block (POSSIBLE, LIKELY, VERY_LIKELY) |
| `RATE_LIMIT_IMAGES_PER_HOUR` | `20` | Max image uploads per hour |
| `RATE_LIMIT_TEXTS_PER_MINUTE` | `60` | Max text messages per minute |
| `VERBOSE_LOGGING` | `true` | Store original content in logs |

### Moderation Thresholds

- `VERY_LIKELY`: Most strict - blocks anything questionable
- `LIKELY`: Default - reasonable threshold
- `POSSIBLE`: More permissive - may miss some inappropriate content

## Testing

```bash
cd functions

# Run all tests
pytest

# Run with coverage
pytest --cov=.

# Run specific test file
pytest tests/test_image_moderation.py
```

## Cost Estimates

### Google Cloud Vision API

| Volume | Cost |
|--------|------|
| First 1,000/month | Free |
| 1,001 - 5,000,000/month | $1.50 per 1,000 |

### Example: 1,000 users × 5 images/day

- Monthly images: 150,000
- Vision API: ~$224/month
- Storage: ~$5-10/month
- Functions: ~$10-20/month

## Security

- All images are moderated server-side before becoming visible
- Client cannot access pending images
- Blocked content is logged but deleted from storage
- User violations are tracked for potential future repeat-offender handling
- Rate limiting prevents abuse and cost spikes

## License

[MIT License](LICENSE)

## Contributing

See [SETUP_GUIDE.md](docs/SETUP_GUIDE.md) for development setup.
