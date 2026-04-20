"""All Playwright selectors in one place.

When 10bis or WhatsApp Web updates their UI, this is the only file to change.
Keep flow modules (tenbis_flow.py, whatsapp.py) completely selector-free.
"""

# ── 10bis ─────────────────────────────────────────────────────────────────────

TENBIS_BASE_URL = "https://www.10bis.co.il/next/en/"
TENBIS_BILLING_URL = "https://www.10bis.co.il/next/en/personal-area?section=my-orders&dateBias=0"

# Login
TENBIS_LOGGED_IN_BUTTON = 'button[aria-label*="Hi,"], button:has-text("Hi,")'
TENBIS_SIGN_IN_BUTTON = 'a[href*="signin"], button:has-text("Sign in"), button:has-text("Log in")'
TENBIS_EMAIL_INPUT = 'input[type="email"], input[placeholder*="email" i]'
TENBIS_LOGIN_SUBMIT = (
    'button[data-test-id="login-submit"], button:has-text("Let\'s Go"), button:has-text("Continue")'
)
TENBIS_OTP_INPUT = 'input[name^="verification-code-"]'
TENBIS_OTP_SUBMIT = 'button[data-test-id="verification-submit"], button:has-text("Verify"), button:has-text("Accept")'  # noqa: E501

# Budget page — labels that appear on the billing report
TENBIS_BUDGET_LABELS_MONTHLY = ["Monthly balance", "Monthly limit"]

# Restaurant / dish page
TENBIS_ADD_TO_CART_BUTTON = 'button[data-test-id="submitDishBtn"], button[data-test-id="add-to-cart"], button:has-text("Add item"), button:has-text("Add to cart"), button:has-text("הוסף לסל")'  # noqa: E501
TENBIS_CART_BUTTON = '[data-test-id="cart-button"], [aria-label*="cart" i], a[href*="checkout"]'
TENBIS_CHECKOUT_BUTTON = 'button:has-text("Proceed to payment"), button:has-text("Checkout"), button:has-text("לתשלום"), a:has-text("Checkout")'

# Checkout page
TENBIS_SUBMIT_ORDER_BUTTON = 'button[data-test-id="submit-order"], button:has-text("Place order"), button:has-text("אישור הזמנה")'  # noqa: E501

# Order confirmation / voucher page — barcode
TENBIS_BARCODE_IMG = '[class*="BarCodeImg"]'
TENBIS_BARCODE_NUMBER = '[class*="BarCodeNumber"]'
# The barcode image is often a CSS background-image; this regex extracts the URL
TENBIS_BARCODE_BG_URL_PATTERN = r'background-image:\s*url\(["\']?([^"\')\s]+)["\']?\)'

# ── WhatsApp Web ───────────────────────────────────────────────────────────────

WHATSAPP_URL = "https://web.whatsapp.com"

# Confirms we are fully logged in (chat list is rendered)
WHATSAPP_LOGGED_IN = "#pane-side"

# Search
WHATSAPP_SEARCH_BOX = '[aria-label="Search or start a new chat"]'
WHATSAPP_SEARCH_INPUT = '[aria-label="Search or start a new chat"]'

# Chat list result item — the span that holds the chat title text
WHATSAPP_CHAT_RESULT_TITLE = 'span[dir="auto"][title]'

# Active chat header — used to validate we opened the right group
WHATSAPP_ACTIVE_CHAT_TITLE = 'header [data-testid="conversation-info-header-chat-title"] span'
# Subtitle shown for groups (e.g. "You, Wife")
WHATSAPP_ACTIVE_CHAT_SUBTITLE = (
    'header [data-testid="conversation-info-header"] [data-testid="subtitle"]'
)

# Attach menu
WHATSAPP_ATTACH_BUTTON = '[aria-label="Attach"]'
# The "Photos & videos" button inside the attach dropdown — clicking this opens a
# native file chooser that routes the upload through the photo pipeline (not stickers).
WHATSAPP_PHOTOS_BUTTON = '[aria-label="Photos & videos"]'

# Caption box in the media preview modal.
# The container itself IS the div[contenteditable] (data-tab is now "undefined").
WHATSAPP_CAPTION_INPUT = (
    '[data-testid="media-caption-input-container"], [aria-label*="Add a caption"]'
)
WHATSAPP_SEND_BUTTON = '[data-testid="send"], [data-testid="media-send"], [aria-label="Send"]'

# Message in conversation — used to locate sent messages for reaction scanning
# The data-id attribute uniquely identifies each message
WHATSAPP_MESSAGE_BY_ID = '[data-id="{message_id}"]'
# Reaction indicator on a message bubble
WHATSAPP_REACTION_CONTAINER = '[data-testid="msg-reactions"], [class*="reaction"]'

# Outgoing text message input
WHATSAPP_TEXT_INPUT = '[aria-label="Type a message"], [aria-label*="Type a message"]'

# Reaction hover button — lives in a global overlay after hovering a message.
# Always query from page root, NOT from the message element.
WHATSAPP_REACTION_HOVER_BUTTON = (
    '[data-testid="emoji-reaction"],'
    '[data-testid="reaction-emoji-button"],'
    '[aria-label="React"],'
    '[aria-label*="React"]'
)

# "+" / expand button inside the quick-tray that opens the full emoji picker
WHATSAPP_REACTION_EXPAND = (
    'button[aria-label="More emojis"],[data-testid="reaction-more"],button[aria-label="+"]'
)

# Full emoji picker — search box and individual result buttons
WHATSAPP_EMOJI_PICKER_SEARCH = '[data-testid="emoji-search-input"],input[placeholder*="Search" i]'
# Parameterised — use .format(emoji="🤖")
WHATSAPP_EMOJI_PICKER_RESULT = 'button[data-emoji="{emoji}"],button[aria-label="{emoji}"]'

# Reaction display on a message bubble
WHATSAPP_MSG_REACTIONS = '[data-testid="msg-reactions"]'
