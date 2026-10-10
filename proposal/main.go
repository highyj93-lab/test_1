// 프로포즈 게임 실행기.
//
// index.html 을 실행 파일 안에 내장하고, 로컬 서버(127.0.0.1)를 띄운 뒤
// Edge/Chrome 을 앱 모드 전체화면으로 열어 보여준다.
// 실행 파일과 같은 폴더에 music.mp3 가 있으면 그 음악을 재생한다.
package main

import (
	_ "embed"
	"fmt"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"sync/atomic"
	"time"
)

//go:embed index.html
var indexHTML string

// 브라우저 창이 닫혔는지 알기 위한 하트비트. 페이지가 3초마다 /ping 을 보낸다.
const heartbeat = `<script>setInterval(()=>fetch('/ping').catch(()=>{}),3000)</script>`

// 백그라운드 탭은 타이머가 1분 단위로 느려질 수 있어 넉넉하게 잡는다.
const idleTimeout = 3 * time.Minute

func main() {
	page := strings.Replace(indexHTML, "</body>", heartbeat+"</body>", 1)
	var lastPing atomic.Int64
	lastPing.Store(time.Now().UnixNano())

	exeDir := "."
	if exe, err := os.Executable(); err == nil {
		exeDir = filepath.Dir(exe)
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/" && r.URL.Path != "/index.html" {
			http.NotFound(w, r)
			return
		}
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		fmt.Fprint(w, page)
	})
	mux.HandleFunc("/music.mp3", func(w http.ResponseWriter, r *http.Request) {
		http.ServeFile(w, r, filepath.Join(exeDir, "music.mp3"))
	})
	mux.HandleFunc("/ping", func(w http.ResponseWriter, r *http.Request) {
		lastPing.Store(time.Now().UnixNano())
		w.WriteHeader(http.StatusNoContent)
	})

	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		fatal("로컬 서버를 시작하지 못했습니다: " + err.Error())
	}
	go http.Serve(ln, mux)
	url := fmt.Sprintf("http://%s/", ln.Addr().String())

	// 앱 모드 브라우저를 직접 띄웠다면 그 창이 닫힐 때 바로 종료
	if cmd := openAppWindow(url); cmd != nil {
		go func() {
			cmd.Wait()
			os.Exit(0)
		}()
	} else {
		openDefaultBrowser(url)
	}

	// 기본 브라우저로 열린 경우 등: 페이지가 닫혀 하트비트가 끊기면 종료
	for range time.Tick(10 * time.Second) {
		if time.Since(time.Unix(0, lastPing.Load())) > idleTimeout {
			os.Exit(0)
		}
	}
}

// Edge 또는 Chrome 을 별도 프로필의 앱 모드(주소창 없음) 전체화면으로 연다.
// 별도 프로필을 써야 기존 브라우저 창에 합쳐지지 않고 창 종료를 감지할 수 있다.
func openAppWindow(url string) *exec.Cmd {
	for _, path := range browserCandidates() {
		if _, err := os.Stat(path); err != nil {
			continue
		}
		profile := filepath.Join(os.TempDir(), "proposal-game-profile")
		cmd := exec.Command(path,
			"--app="+url,
			"--start-fullscreen",
			"--user-data-dir="+profile,
			"--no-first-run",
			"--no-default-browser-check",
			"--autoplay-policy=no-user-gesture-required",
		)
		if err := cmd.Start(); err == nil {
			return cmd
		}
	}
	return nil
}

func browserCandidates() []string {
	switch runtime.GOOS {
	case "windows":
		var out []string
		for _, env := range []string{"ProgramFiles(x86)", "ProgramFiles", "LocalAppData"} {
			base := os.Getenv(env)
			if base == "" {
				continue
			}
			out = append(out,
				filepath.Join(base, `Microsoft\Edge\Application\msedge.exe`),
				filepath.Join(base, `Google\Chrome\Application\chrome.exe`),
			)
		}
		return out
	case "darwin":
		return []string{
			"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
			"/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
		}
	default:
		var out []string
		for _, name := range []string{"google-chrome", "chromium", "chromium-browser", "microsoft-edge"} {
			if p, err := exec.LookPath(name); err == nil {
				out = append(out, p)
			}
		}
		return out
	}
}

func openDefaultBrowser(url string) {
	var cmd *exec.Cmd
	switch runtime.GOOS {
	case "windows":
		cmd = exec.Command("rundll32", "url.dll,FileProtocolHandler", url)
	case "darwin":
		cmd = exec.Command("open", url)
	default:
		cmd = exec.Command("xdg-open", url)
	}
	if err := cmd.Start(); err != nil {
		fatal("브라우저를 열지 못했습니다. 직접 접속해 주세요: " + url)
	}
}

func fatal(msg string) {
	fmt.Fprintln(os.Stderr, msg)
	os.Exit(1)
}
