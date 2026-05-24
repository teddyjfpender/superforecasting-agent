class SuperforecastingAgent < Formula
  include Language::Python::Virtualenv

  desc "Command-line forecasting desk that compounds judgment over time"
  homepage "https://github.com/teddyjfpender/superforecasting-agent"
  # Stable source should point at the semver-named sdist asset attached by
  # scripts/release.py, not the CalVer tag tarball.
  url "https://github.com/teddyjfpender/superforecasting-agent/releases/download/v2026.5.24/superforecasting_agent-0.14.0.tar.gz"
  sha256 "<replace-with-release-asset-sha256>"
  license "MIT"

  depends_on "certifi" => :no_linkage
  depends_on "cryptography" => :no_linkage
  depends_on "libyaml"
  depends_on "python@3.14"

  pypi_packages ignore_packages: %w[certifi cryptography pydantic]

  # Refresh resource stanzas after bumping the source url/version:
  #   brew update-python-resources --print-only superforecasting-agent

  def install
    venv = virtualenv_create(libexec, "python3.14")
    venv.pip_install resources
    venv.pip_install buildpath

    pkgshare.install "skills", "optional-skills"

    %w[
      forecast
      superforecast
      superforecasting-agent
      superforecasting-agent-acp
      superforecast-acp
      hermes
      hermes-agent
      hermes-acp
    ].each do |exe|
      next unless (libexec/"bin"/exe).exist?

      (bin/exe).write_env_script(
        libexec/"bin"/exe,
        SUPERFORECASTING_AGENT_BUNDLED_SKILLS: pkgshare/"skills",
        FORECAST_BUNDLED_SKILLS: pkgshare/"skills",
        HERMES_BUNDLED_SKILLS: pkgshare/"skills",
        SUPERFORECASTING_AGENT_OPTIONAL_SKILLS: pkgshare/"optional-skills",
        FORECAST_OPTIONAL_SKILLS: pkgshare/"optional-skills",
        HERMES_OPTIONAL_SKILLS: pkgshare/"optional-skills",
        SUPERFORECASTING_AGENT_MANAGED: "homebrew",
        FORECAST_MANAGED: "homebrew",
        HERMES_MANAGED: "homebrew"
      )
    end
  end

  test do
    assert_match "Superforecasting Agent v#{version}", shell_output("#{bin}/superforecasting-agent version")

    managed = shell_output("#{bin}/superforecasting-agent update 2>&1")
    assert_match "managed by Homebrew", managed
    assert_match "brew upgrade superforecasting-agent", managed
  end
end
