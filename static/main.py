import webview


if __name__ == '__main__':
    webview.create_window(
        'Kauguru vidusskola App',
        '/home/zeta/Documents/Kaugru-Vidusskola-site/static/web/index.html',
        width=1200,
        height=900
    )

    webview.start()