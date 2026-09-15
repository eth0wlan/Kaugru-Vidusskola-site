import webview


if __name__ == '__main__':
    webview.create_window(
        'Debug window',
        '/home/zeta/Desktop/project/static/web/index.html',
        width=800,
        height=600
    )

    webview.start()