# OllamaBuntu : menu de l'appliance à la connexion sur la console locale
case $- in *i*) ;; *) return 0 2>/dev/null || exit 0 ;; esac
if [ -z "${OB_NO_MENU:-}" ] && [ "$(id -u)" -ne 0 ] && [ -x /usr/local/sbin/ollamabuntu-setup ]; then
  case "$(tty 2>/dev/null)" in
    /dev/tty[1-6]|/dev/ttyS*)
      if id -nG 2>/dev/null | grep -qw sudo; then
        export OB_NO_MENU=1
        sudo -n /usr/local/sbin/ollamabuntu-setup menu
        [ $? -eq 10 ] && exit 0
        echo "Menu de l'appliance : ollamabuntu-menu"
      fi ;;
  esac
fi
