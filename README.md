# XRPL Money Market Application

DISCLAIMER: This minimum viable product (MVP) is solely a demonstration of constructing a money market within the constraints of the XRPL. Designed for a hackathon, it prioritizes functionality over security. Be advised: current security measures are insufficient for production deployment. Should this project advance or be considered for real-world application, stringent security practices will be implemented to mitigate all known risks.

## Overview

This application serves as an MVP for an AAVE-style money market specifically designed for stablecoins or even CBDCs. While this initial product has been designed for retail users, the platform is flexible enoug that it could also be deployed by Central Banks. Central Banks can deploy and manage these permissioned platforms, interacting with existing tokens on the DEX or by opening trust lines between institutions.

Built on the XRP Ledger (XRPL), the application provides a comprehensive suite of tools and features, from wallet management to seamless transactions, all within a secure and user-friendly interface.

## Features

### Wallet Management
- **Create and Manage Wallets**: Users can easily create and manage their XRPL wallets within the platform.
- **Secure Storage**: Wallet details are securely stored, ensuring the confidentiality and integrity of user information.

### Borrowing and Lending
- **Borrow Assets**: Users can borrow various assets within the XRPL network, including stablecoins and XRP, under defined terms and conditions.
- **Provide Assets to Earn Interest**: Users have the opportunity to provide their assets to the platform's liquidity pool, earning interest on their holdings.
- **Interest Rate Management**: Dynamic interest rates are calculated based on supply and demand, offering competitive returns for lenders and fair rates for borrowers.

### Send Payments
- **Multi-Asset Support**: The platform supports seamless transactions in various assets within the XRPL network.
- **Real-Time Transactions**: Users can enjoy real-time updates and tracking of their transactions.

### User Authentication
- **Secure Access**: Robust login and logout functionalities provide secure access to the platform.
- **Personalized Features**: Users can customize their experience and settings, tailoring the platform to their individual needs and preferences.


### Price Feeds
The pricefeed.py script fetches real-time market prices from Bitso and Bitstamp APIs to determine the exchange rates between supported assets like XRP, BTC, ETH and stablecoins. This enables accurate calculations for interest rates, collateralization ratios etc. based on up-to-date pricing data.

These features collectively provide a comprehensive and user-friendly interface for borrowing, lending, and interacting with the XRPL, making it accessible to both novice and experienced users alike.


## Setup

### XRPMM Wallet

We've built a companion wallet to be able to interact with the platform. The private repo can be found here: [https://github.com/SixtantIO/xrpmm-wallet-public](https://github.com/SixtantIO/xrpmm-wallet-public)

### Prerequisites
- Python 3.6 or higher
- Flask
- Flask-Login
- Flask-SocketIO
- SQLite

### Installation

1. Clone the repository.
2. Navigate to the project directory.
3. Install the required dependencies:

   \`\`\`bash
   pip install -r requirements.txt
   \`\`\`

4. Run the application:

   \`\`\`bash
   python app.py
   \`\`\`

## Usage

### User Registration

1. **Sign Up**: Visit the registration page and fill out the required details.
2. **Verify Email**: Confirm your email address through the verification link sent to your inbox.
3. **Log In**: Use your credentials to log in to the platform.

### Interaction with the Platform

Once logged in, users can explore and utilize various features of the platform:

- **Wallet Management**: Create, load, and manage XRPL wallets.
- **Send Payments**: Seamlessly send payments in CBDCs, XRP, or other assets.
- **View Transactions**: Monitor transaction history and payment status.
- **Settings & Security**: Customize user preferences and enhance security measures.

The platform's intuitive interface ensures a smooth experience, whether you are engaging with CBDCs or conducting transactions within the XRPL network.

## Contributing

Feel free to contribute by submitting pull requests or reporting issues.

## License

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.

The GPL v3.0 License allows you to use and modify the code, but you must also distribute the source code and any modifications under the same license. This ensures that any derivative work remains open source and under the GPL.
