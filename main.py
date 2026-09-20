import webview


if __name__ == '__main__':
    webview.create_window(
        'Kauguru vidusskola App',
        'https://eth0wlan.space',
        width=1200,
        height=900
    )

    webview.start()